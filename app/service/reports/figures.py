import asyncio
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models.dto.report import FigureCreatedOut, FigureOut, FigureSummaryOut, ReportUsageOut
from app.models.entity.user import UserEntity
from app.models.orm.report_figure import ReportFigureOrm
from app.models.orm.run import RunOrm
from app.repo.run_repo import RunRepo
from app.service.ai.usage import UsageService
from app.service.reports.chart_spec import compile_stored, panels_from_stored
from app.service.reports.narrative import chat_completions_url
from app.service.reports.figure_scope import asked_group, asks_ambient, chart_route, prepare_records, uses_fixed_charts
from app.service.reports.presets import PRESETS, fail_names, run_preset, test_rows
from app.service.reports.sandbox import read_result, reject_code, run_in_sandbox
from app.service.reports.store import reports_dir
from app.service.runs.cluster_ingest import fleet_machine_ids
from app.service.runs.run_service import RunService

_PROMPT = """你是批次报告的分析员。用户给了一句要求，你只写一段 Python。
runs 的列是 batch_id、machine_id、slot_index、serial_number、status、passed、fail_items、ended_at、deltas、ambient。fail_items 用顿号拼接。ambient 是室温 ℃，没有则是 null。
deltas 只包含这次要分析的温差，不含热阻。每项是 item、value、low、high、limited。不要分析 rc。没有出现在 deltas 里的项不要填 0。limited 为 false 时只画实测值，不要写超限。
fails 每个不合格项一行，列是 batch_id、machine_id、slot_index、serial_number、item。fails 可能是 None，那时自己拆 fail_items。
定义 analyze(runs, fails=None)，返回 dict，包含 title、panels、results。
panels 最多 4 个。每个是对象，type 只能是 boxplot、scatter、bar、line、heatmap、pareto。
boxplot、bar、line、pareto 要有 categories 和 series。series[].data 里，箱线是 [min, q1, median, q3, max]，其余是数值。
scatter 的 series[].data 是 [[x, y], ...]。横轴是槽位时，x 写成「M01 槽1」，只放有片子的槽，不要用 slot_index 的连续数字。heatmap 要有 x_labels、y_labels、data，data 是 [[x下标, y下标, 值], ...]。
需要参考线时写 marks: [{"name": "均值", "y": 1.2}]。
results 是若干 ["名称", "值"]。不要编造 p 值。要比较两组时另写 tests，例如 {"y":"Temp_T0-T1","by":"batch_id","left":"A","right":"B"}。y 用 deltas 里的 item，by 只能是 batch_id、machine_id、slot_index、passed。
只有上面的类型表达不了时，才返回 echarts_option，而且只能是数据，不能有函数。需要图片时用 matplotlib 保存到 /out/figure.png。
不要使用 os、subprocess、socket，不要联网。
返回 json，code 是 Python 源码，title 是短标题。代码尽量短，直接给结果，不要长篇说明。
"""


def batch_key(batch_ids: list[str]) -> str:
    return ",".join(sorted({item.strip() for item in batch_ids if item and item.strip()}))


class FigureService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, batch_ids: list[str], prompt: str, user: UserEntity, preset: str = "") -> FigureCreatedOut:
        ids = [item.strip() for item in batch_ids if item and item.strip()]
        kind = preset.strip()
        text = prompt.strip()
        if not ids:
            raise AppError(400, "BAD_REQUEST", "batch_ids 不能为空")
        if kind:
            known = PRESETS.get(kind)
            if known is None:
                raise AppError(400, "BAD_REQUEST", "没有这种分析")
            text = known.label
        elif not text:
            raise AppError(400, "BAD_REQUEST", "分析要求不能为空")
        elif len(text) > 200:
            raise AppError(400, "BAD_REQUEST", "分析要求不能超过 200 字")
        stamp = now_ms()
        row = ReportFigureOrm(
            figure_id=f"fig_{uuid4().hex[:8]}",
            batch_key=batch_key(ids),
            batch_ids=ids,
            prompt=text,
            preset=kind,
            status="running",
            step="正在准备数据",
            created_at=stamp,
            updated_at=stamp,
            model="" if kind else (settings.anthropic_model or "deepseek-flash"),
        )
        self.session.add(row)
        await self.session.commit()
        return FigureCreatedOut(figure_id=row.figure_id)

    async def get(self, figure_id: str) -> FigureOut:
        row = await self._row(figure_id)
        await self._expire(row)
        return await self._shown(row)

    async def list_for(self, batch_ids: str) -> list[FigureOut]:
        key = batch_key(batch_ids.split(","))
        if not key:
            return []
        rows = (await self.session.scalars(select(ReportFigureOrm).where(ReportFigureOrm.batch_key == key).order_by(ReportFigureOrm.created_at))).all()
        shown = []
        records: list[dict] | None = None
        for row in rows:
            await self._expire(row)
            if row.status == "done" and (row.preset or _needs_summary(row.prompt)):
                if records is None:
                    records = await self._records(row.batch_ids)
            shown.append(await self._shown(row, records))
        return shown

    async def delete(self, figure_id: str) -> None:
        row = await self._row(figure_id)
        if row.png_name:
            path = reports_dir() / row.png_name
            path.unlink(missing_ok=True)
        await self.session.delete(row)
        await self.session.commit()

    async def run(self, figure_id: str, user_name: str) -> None:
        row = await self.session.get(ReportFigureOrm, figure_id)
        if row is None or row.status != "running":
            return
        input_tokens = 0
        output_tokens = 0
        model_name = row.model
        error = ""
        used_model = False
        try:
            records = await self._records(row.batch_ids)
            if not records:
                raise AppError(400, "BAD_REQUEST", "所选批次还没有测完的片子")
            prepared = prepare_records(row.prompt, records, delta=bool(row.preset))
            if prepared.summary is not None and not prepared.records:
                raise AppError(400, "BAD_REQUEST", "；".join(prepared.notes) or "没有可画的温差")
            group = "" if row.preset else asked_group(row.prompt)
            fixed = row.preset or chart_route(row.prompt)
            if fixed:
                await self._step(row, "正在计算")
                result = await asyncio.to_thread(run_preset, fixed, prepared.records, group, asks_ambient(row.prompt))
                _apply_result(row, result, None, prepared.records, prepared.summary)
                row.model = "builtin"
            else:
                used_model = True
                await self._run_model(row, prepared.records, prepared.summary)
                input_tokens = row.input_tokens
                output_tokens = row.output_tokens
                model_name = row.model

        except AppError as exc:
            error = exc.message
        except Exception:
            error = "分析没有完成"
        row.updated_at = now_ms()
        if error:
            row.status = "failed"
            row.error = error
            row.step = "分析没有完成"
        else:
            row.status = "done"
            row.error = ""
            row.step = "done"
        if used_model:
            row.model = model_name
            row.input_tokens = input_tokens
            row.output_tokens = output_tokens
            await UsageService(self.session).record(
                module="report",
                user=user_name,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=max(now_ms() - row.created_at, 1),
                ok=not error,
                ref={"figure_id": figure_id, "batch_ids": row.batch_ids},
            )
        await self.session.commit()

    async def _run_model(self, row: ReportFigureOrm, records: list[dict], summary: dict | None) -> None:
        from app.service.settings.model import configured_model

        chosen = await configured_model(self.session)
        await self._step(row, "正在让模型写分析代码")
        code, title, input_tokens, output_tokens, model_name = await _request_code(row.prompt, records, "", chosen)
        blocked = reject_code(code)
        if blocked:
            code, title, extra_in, extra_out, model_name = await _request_code(row.prompt, records, blocked, chosen)
            input_tokens += extra_in
            output_tokens += extra_out
            blocked = reject_code(code)
        if blocked:
            raise AppError(502, "AGENT_FAILED", blocked)
        row.code = code
        row.title = title
        await self._step(row, "在沙箱执行 Python")
        result, png, failure = await asyncio.to_thread(_execute, row.figure_id, records, code)
        if not failure:
            failure = _chart_problem(result, png)
        if failure:
            await self._step(row, "模型正在生成代码，绘制中。")
            code, title, extra_in, extra_out, model_name = await _request_code(row.prompt, records, failure, chosen)
            input_tokens += extra_in
            output_tokens += extra_out
            if reject_code(code):
                raise AppError(502, "AGENT_FAILED", "重写后的代码仍然不能执行")
            row.code = code
            row.title = title or row.title
            await self._step(row, "在沙箱执行 Python")
            result, png, failure = await asyncio.to_thread(_execute, row.figure_id, records, code)
            if not failure:
                failure = _chart_problem(result, png)
        if failure:
            raise AppError(502, "AGENT_FAILED", _public_failure(failure))
        await self._step(row, "正在读取结果")
        _apply_result(row, result, png, records, summary)
        row.model = model_name
        row.input_tokens = input_tokens
        row.output_tokens = output_tokens

    async def _records(self, batch_ids: list[str]) -> list[dict]:
        runs = RunService(self.session)
        await runs._ensure_fleet()
        rows = await RunRepo(self.session).list_by_batches(batch_ids, fleet_machine_ids() or None)
        rows = rows[:5000]
        from app.service.reports.analysis_service import AnalysisService

        limits = await AnalysisService(self.session)._limits(rows)
        return [_record(row, limits.get((row.plan_id, int(row.plan_version or 0))) or {}) for row in rows]

    async def _shown(self, row: ReportFigureOrm, records: list[dict] | None = None) -> FigureOut:
        out = _out(row)
        if row.status != "done" or not (row.preset or _needs_summary(row.prompt)):
            return out
        if records is None:
            records = await self._records(row.batch_ids)
        prepared = prepare_records(row.prompt, records, delta=bool(row.preset))
        if prepared.summary:
            out.summary = FigureSummaryOut.model_validate(prepared.summary)
        return out

    async def _step(self, row: ReportFigureOrm, text: str) -> None:
        row.step = text
        row.updated_at = now_ms()
        await self.session.commit()

    async def _row(self, figure_id: str) -> ReportFigureOrm:
        row = await self.session.get(ReportFigureOrm, figure_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", "这张图不存在")
        return row

    async def _expire(self, row: ReportFigureOrm) -> None:
        if row.status == "running" and now_ms() - row.updated_at > 180_000:
            row.status = "failed"
            row.error = "分析没有完成"
            row.step = "分析没有完成"
            await self.session.commit()


def _needs_summary(prompt: str) -> bool:
    return uses_fixed_charts(prompt)


async def execute_figure(figure_id: str, user_name: str) -> None:
    async with SessionLocal() as session:
        await FigureService(session).run(figure_id, user_name)


def _sandbox_temp_dir(figure_id: str) -> Path:
    root = os.environ.get("SANDBOX_ROOT", "").strip()
    if root:
        path = Path(root)
        path.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f"vcos-{figure_id}-", dir=path))
    return Path(tempfile.mkdtemp(prefix=f"vcos-{figure_id}-"))


def _execute(figure_id: str, records: list[dict], code: str) -> tuple[dict, Path | None, str]:
    root = _sandbox_temp_dir(figure_id)
    work = root / "work"
    out = root / "out"
    work.mkdir()
    out.mkdir()
    try:
        (work / "runs.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        (work / "fails.json").write_text(json.dumps(_fail_rows(records), ensure_ascii=False), encoding="utf-8")
        (work / "code.py").write_text(code, encoding="utf-8")
        failure = run_in_sandbox(work, out)
        if failure:
            return {}, None, failure
        result, has_png = read_result(out)
        png = None
        if has_png:
            dest = reports_dir() / f"{figure_id}.png"
            shutil.copyfile(out / "figure.png", dest)
            png = dest
        return result, png, ""
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _apply_result(row: ReportFigureOrm, result: dict, png: Path | None, records: list[dict], summary: dict | None = None) -> None:
    title = str(result.get("title") or row.title or row.prompt)[:40]
    panels, problem = compile_stored(result)
    results = [] if summary else _pairs(result.get("results"))
    if not summary:
        results.extend(test_rows(records, result.get("tests")))
    if not panels and png is None:
        raise AppError(502, "AGENT_FAILED", problem or "没有生成图表")
    row.title = title
    stored: dict = {"panels": panels}
    if summary:
        stored["summary"] = summary
    row.echarts_option = stored if panels or summary else None
    row.results = results[:16]
    row.png_name = png.name if png else ""


def _public_failure(failure: str) -> str:
    if len(failure) > 180 or "Traceback" in failure or failure == "没有生成图表":
        return "沙箱没有算出结果"
    return failure


def _chart_problem(result: dict, png: Path | None) -> str:
    if png is not None:
        return ""
    panels, problem = compile_stored(result if isinstance(result, dict) else {})
    if not panels:
        return problem or "没有生成图表"
    if _values_are_all_zero(panels):
        return "图上的值全是 0。数据里没有的项不要填 0，删掉该项后重画。"
    return ""


def _values_are_all_zero(panels: list[dict]) -> bool:
    numbers: list[float] = []

    def collect(value: object) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            numbers.append(float(value))
            return
        if isinstance(value, list):
            for item in value:
                collect(item)

    for panel in panels:
        option = panel.get("option") if isinstance(panel, dict) else None
        if not isinstance(option, dict):
            continue
        for series in option.get("series") or []:
            if isinstance(series, dict):
                collect(series.get("data"))
    return bool(numbers) and all(number == 0 for number in numbers)


def _pairs(raw: object) -> list[list[str]]:
    rows: list[list[str]] = []
    if not isinstance(raw, list):
        return rows
    for item in raw[:16]:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            rows.append([str(item[0])[:40], str(item[1])[:80]])
    return rows


def _fail_rows(records: list[dict]) -> list[dict]:
    rows = []
    for record in records:
        for name in fail_names(record.get("fail_items")):
            rows.append({
                "batch_id": record.get("batch_id") or "",
                "machine_id": record.get("machine_id") or "",
                "slot_index": record.get("slot_index"),
                "serial_number": record.get("serial_number") or "",
                "item": name,
            })
    return rows


def _record(row: RunOrm, spec: dict | None = None) -> dict:
    return {
        "batch_id": row.batch_id,
        "machine_id": row.machine_id,
        "slot_index": row.slot_index,
        "serial_number": row.serial_number,
        "status": row.status,
        "passed": row.passed,
        "fail_items": "、".join(row.fail_items or []),
        "ended_at": row.ended_at,
        "deltas": limit_deltas(row, spec or {}),
        "measured": measured_deltas(row),
        "ambient": _ambient_value(row),
    }


def limit_deltas(row: RunOrm, spec: dict) -> list[dict]:
    from app.service.reports.analysis_math import item_sort_key, usable
    from app.service.reports.analysis_service import _measured

    measured = _measured(row)
    entries = []
    if spec:
        order = 0
        for key, item in spec.items():
            key = str(key)
            if not key.startswith("delta_") and key not in {"power_w", "temp_ambient"}:
                continue
            name, low, high = item
            raw = _ambient_value(row) if key == "temp_ambient" else measured.get(key)
            if raw is None or not usable(raw):
                continue
            entries.append({"item": name, "value": float(raw), "low": low, "high": high, "limited": True, "order": order})
            order += 1
    else:
        for key, raw in measured.items():
            if not str(key).startswith("delta_") or not usable(raw):
                continue
            entries.append({"item": _delta_label(str(key)), "value": float(raw), "low": None, "high": None, "limited": False})
    entries.sort(key=lambda item: (item.get("order", 10**9), item_sort_key(str(item["item"]))))
    return entries


def measured_deltas(row: RunOrm) -> list[dict]:
    from app.service.reports.analysis_math import item_sort_key, usable
    from app.service.reports.analysis_service import _measured

    entries = []
    for key, raw in _measured(row).items():
        if not str(key).startswith("delta_") or not usable(raw):
            continue
        entries.append({"item": _delta_label(str(key)), "value": float(raw)})
    entries.sort(key=lambda item: item_sort_key(str(item["item"])))
    return entries


def _ambient_value(row: RunOrm) -> float | None:
    from app.service.reports.analysis_math import usable

    result = row.result if isinstance(row.result, dict) else {}
    deltas = result.get("deltas") or {}
    if isinstance(deltas, dict):
        for key in ("Temp_Ta", "Ta", "temp_ambient"):
            value = deltas.get(key)
            if usable(value):
                return float(value)
    for item in result.get("temps") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("channel") or item.get("item") or "").lower()
        if name in {"ta", "t_a", "ambient"}:
            value = item.get("value")
            if usable(value):
                return float(value)
    return None


def _delta_label(key: str) -> str:
    parts = key.removeprefix("delta_").split("_")
    numbers = [part[1:] for part in parts if part.startswith("t") and part[1:].isdigit()]
    if len(numbers) == 2:
        return f"Temp_T{numbers[0]}-T{numbers[1]}"
    return key


def _out(row: ReportFigureOrm) -> FigureOut:
    stored = row.echarts_option if isinstance(row.echarts_option, dict) else {}
    panels = panels_from_stored(stored)
    summary = stored.get("summary") if isinstance(stored.get("summary"), dict) else None
    return FigureOut(
        figure_id=row.figure_id,
        status=row.status,
        prompt=row.prompt,
        title=row.title,
        echarts_option=panels[0]["option"] if panels else None,
        panels=panels,
        png_url=f"/api/v1/reports/figures/{row.figure_id}.png" if row.png_name else None,
        code=row.code,
        results=row.results or [],
        summary=summary,
        usage=ReportUsageOut(input=row.input_tokens, output=row.output_tokens),
        error=row.error or None,
        step=row.step,
    )


async def _request_code(prompt: str, records: list[dict], failure: str, model: str | None = None) -> tuple[str, str, int, int, str]:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    model = (model or settings.anthropic_model or "deepseek-flash").strip()
    sample = json.dumps(records[:3], ensure_ascii=False)
    content = f"{_PROMPT}\n行数：{len(records)}\n样例：{sample}\n用户要求：{prompt}"
    if failure:
        content += f"\n上次没有成功，错误是：{failure[-1500:]}\n请重写 analyze。"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
        "max_tokens": 8000,
    }
    input_tokens = 0
    output_tokens = 0
    model_name = model
    text = ""
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(
                    chat_completions_url(settings.anthropic_base_url),
                    headers={"Authorization": f"Bearer {settings.anthropic_api_key}"},
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise AppError(502, "AGENT_FAILED", "分析请求没有完成") from exc
        if response.status_code >= 400:
            raise AppError(502, "AGENT_FAILED", "分析请求没有完成")
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AppError(502, "AGENT_FAILED", "模型没有返回分析代码") from exc
        input_tokens += int(usage.get("prompt_tokens") or 0)
        output_tokens += int(usage.get("completion_tokens") or 0)
        model_name = str(data.get("model") or model)
        if isinstance(text, str) and text.strip():
            break
    if not isinstance(text, str) or not text.strip():
        raise AppError(502, "AGENT_FAILED", "模型没有返回分析代码")
    code, title = _code_from(text)
    if "def analyze" not in code:
        raise AppError(502, "AGENT_FAILED", "模型没有返回分析代码")
    return code[:12000], title, input_tokens, output_tokens, model_name


def _code_from(text: str) -> tuple[str, str]:
    raw = text.strip()
    start = raw.find("{")
    if start < 0:
        raise AppError(502, "AGENT_FAILED", "模型没有返回分析代码")
    try:
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as exc:
        raise AppError(502, "AGENT_FAILED", "模型没有返回分析代码") from exc
    code = str(data.get("code") or "")
    fenced = re.search(r"```(?:python)?\s*(.*?)```", code, re.S)
    if fenced:
        code = fenced.group(1)
    return code.strip(), str(data.get("title") or "").strip()[:40]
