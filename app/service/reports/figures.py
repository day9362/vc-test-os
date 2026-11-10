import asyncio
import json
import logging
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
from app.models.dto.report import FigureCreatedOut, FigureOut, FigureQuestionOut, FigureSummaryOut, FigureTableOut, ReportUsageOut
from app.models.entity.user import UserEntity
from app.models.orm.report_figure import ReportFigureOrm
from app.models.orm.run import RunOrm
from app.repo.run_repo import RunRepo
from app.service.ai.usage import UsageService
from app.service.reports.chart_spec import compile_stored, panels_from_stored
from app.service.reports.narrative import chat_completions_url
from app.service.reports.figure_dialog import (
    MAX_RUNS,
    PROCESS_COLUMNS,
    _PROMPT,
    catalog_text,
    filter_records,
    keep_columns,
    narrow_question,
    parse_model_payload,
    thin_points,
    too_many,
)
from app.service.reports.figure_scope import asked_group, asks_ambient, prepare_records
from app.service.reports.presets import PRESETS, fail_names, run_preset, test_rows
from app.service.reports.sandbox import read_result, reject_code, run_in_sandbox
from app.service.reports.store import reports_dir
from app.service.runs.cluster_ingest import fleet_machine_ids
from app.service.runs.run_service import RunService

logger = logging.getLogger(__name__)
_STALE_MS = 180_000
_FETCH_AT_ONCE = 8

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
        rows = (await self.session.scalars(select(ReportFigureOrm).where(ReportFigureOrm.batch_key == key).order_by(ReportFigureOrm.created_at.desc()))).all()
        shown = []
        records: list[dict] | None = None
        for row in rows:
            await self._expire(row)
            if row.status == "done" and row.preset:
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
            if row.preset and prepared.summary is not None and not prepared.records:
                raise AppError(400, "BAD_REQUEST", "；".join(prepared.notes) or "没有可画的温差")
            group = "" if row.preset else asked_group(row.prompt)
            fixed = row.preset
            if fixed:
                await self._step(row, "正在计算")
                result = await asyncio.to_thread(run_preset, fixed, prepared.records, group, asks_ambient(row.prompt))
                _apply_result(row, result, None, prepared.records, prepared.summary)
                row.model = "builtin"
            else:
                used_model = True
                await self._run_free(row, records)
                input_tokens = row.input_tokens
                output_tokens = row.output_tokens
                model_name = row.model

        except AppError as exc:
            error = exc.message
        except Exception as exc:
            logger.exception("figure %s failed", figure_id)
            error = (str(exc).strip().splitlines() or [exc.__class__.__name__])[0][:180]
        row.updated_at = now_ms()
        if error:
            row.status = "failed"
            row.error = error
            row.step = error
        elif row.status != "asking":
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

    async def answer(self, figure_id: str, text: str, picks: list[str]) -> None:
        row = await self._row(figure_id)
        if row.preset or row.status != "asking":
            raise AppError(400, "BAD_REQUEST", "这张图现在不能补充")
        message = _reply_text(text, picks)
        if not message:
            raise AppError(400, "BAD_REQUEST", "补充不能为空")
        thread = list(row.thread or [])
        thread.append({"role": "user", "content": message[:500]})
        row.thread = thread
        row.questions = []
        row.note = ""
        row.status = "running"
        row.error = ""
        row.step = "正在准备数据"
        row.updated_at = now_ms()
        await self.session.commit()

    async def _run_free(self, row: ReportFigureOrm, records: list[dict]) -> None:
        from app.service.settings.model import configured_model

        chosen = await configured_model(self.session)
        catalog = catalog_text(records)
        must_draw = int(row.ask_round or 0) >= 3
        await self._step(row, "正在让模型看目录")
        payload, input_tokens, output_tokens, model_name = await self._wait(row, _request_turn(row, catalog, "", chosen))
        if must_draw and payload["kind"] != "draw":
            payload, extra_in, extra_out, model_name = await self._wait(
                row,
                _request_turn(row, catalog, "三轮问题已经问完。必须返回 code 出图，不要 questions。", chosen),
            )
            input_tokens += extra_in
            output_tokens += extra_out
        if payload["kind"] == "draw":
            selected = filter_records(records, payload["slice"])
            truncated = False
            if not selected and must_draw:
                selected = records[:MAX_RUNS]
                truncated = len(records) > MAX_RUNS
            elif too_many(selected):
                if must_draw:
                    truncated = True
                    selected = selected[:MAX_RUNS]
                else:
                    payload = {"kind": "ask", "questions": [narrow_question(selected)], "hint": {"need": "先缩小到不超过 200 条", "allow": "可以指定机台、槽位或序列号"}}
            if payload["kind"] == "draw":
                await self._draw(row, selected, payload, chosen, input_tokens, output_tokens, model_name, catalog, must_draw)
                if truncated:
                    row.note = "超过 200 条，这张图用了其中前 200 条。"
                return
        if must_draw:
            raise AppError(502, "AGENT_FAILED", "第三轮没有写出图")
        _remember_ask(row, payload)
        row.model = model_name
        row.input_tokens = input_tokens
        row.output_tokens = output_tokens

    async def _draw(self, row, records, payload, chosen, input_tokens, output_tokens, model_name, catalog, force: bool = False) -> None:
        code = payload["code"]
        blocked = reject_code(code)
        if blocked:
            payload, extra_in, extra_out, model_name = await self._wait(row, _request_turn(row, catalog, blocked, chosen))
            input_tokens += extra_in
            output_tokens += extra_out
            if payload["kind"] != "draw":
                if force:
                    raise AppError(502, "AGENT_FAILED", "第三轮没有写出图")
                _remember_ask(row, payload)
                row.model = model_name
                row.input_tokens = input_tokens
                row.output_tokens = output_tokens
                return
            code = payload["code"]
            if reject_code(code):
                raise AppError(502, "AGENT_FAILED", "重写后的代码仍然不能执行")
        row.code = code
        row.title = payload.get("title") or row.title
        samples = await self._process_slice(row, records, payload["slice"])
        await self._step(row, "在沙箱执行 Python")
        result, png, failure = await self._wait(row, asyncio.to_thread(_execute, row.figure_id, records, samples, code))
        if not failure:
            failure = _chart_problem(result, png)
        if failure:
            payload, extra_in, extra_out, model_name = await self._wait(row, _request_turn(row, catalog, failure[-1500:], chosen))
            input_tokens += extra_in
            output_tokens += extra_out
            if payload["kind"] != "draw" or reject_code(payload["code"]):
                raise AppError(502, "AGENT_FAILED", _public_failure(failure))
            code = payload["code"]
            row.code = code
            row.title = payload.get("title") or row.title
            samples = await self._process_slice(row, records, payload.get("slice") or {})
            await self._step(row, "在沙箱执行 Python")
            result, png, failure = await self._wait(row, asyncio.to_thread(_execute, row.figure_id, records, samples, code))
            if not failure:
                failure = _chart_problem(result, png)
        if failure:
            raise AppError(502, "AGENT_FAILED", _public_failure(failure))
        await self._step(row, "正在读取结果")
        _apply_result(row, result, png, records, None)
        row.questions = []
        row.note = ""
        row.model = model_name
        row.input_tokens = input_tokens
        row.output_tokens = output_tokens

    async def _process_slice(self, row: ReportFigureOrm, records: list[dict], spec: dict) -> list[dict]:
        columns = [str(item) for item in (spec.get("columns") or [])]
        full_curve = spec.get("full_curve") is True
        if not _needs_process(columns, full_curve):
            return []
        from app.service.runs.result_csv import points_from_body

        runs = RunService(self.session)
        run_ids: list[str] = []
        seen: set[str] = set()
        for record in records:
            run_id = str(record.get("run_id") or "")
            if not run_id or run_id in seen:
                continue
            seen.add(run_id)
            run_ids.append(run_id)
        gate = asyncio.Semaphore(_FETCH_AT_ONCE)

        async def load(run_id: str) -> tuple[str, list[dict]]:
            async with gate:
                body = await runs._sample_rows(run_id)
            stamped = []
            for point in points_from_body(body):
                point["run_id"] = run_id
                stamped.append(point)
            return run_id, stamped

        tasks = [asyncio.create_task(load(run_id)) for run_id in run_ids]
        pending = set(tasks)
        found: dict[str, list[dict]] = {}
        try:
            while pending:
                done, pending = await asyncio.wait(pending, timeout=20, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    await self._touch(row)
                    continue
                for task in done:
                    run_id, stamped = task.result()
                    found[run_id] = stamped
                await self._touch(row)
        except Exception:
            for task in tasks:
                task.cancel()
            raise
        points = [point for run_id in run_ids for point in found.get(run_id, [])]
        return thin_points(keep_columns(points, columns), full_curve)

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
        if row.status != "done" or not row.preset:
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

    async def _touch(self, row: ReportFigureOrm) -> None:
        stamp = now_ms()
        row.updated_at = stamp
        async with SessionLocal() as session:
            current = await session.get(ReportFigureOrm, row.figure_id)
            if current is None or current.status != "running":
                return
            current.updated_at = stamp
            await session.commit()

    async def _wait(self, row: ReportFigureOrm, work):
        task = asyncio.create_task(work)
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=20)
                if not task.done():
                    await self._touch(row)
            return task.result()
        except asyncio.CancelledError:
            task.cancel()
            raise

    async def _row(self, figure_id: str) -> ReportFigureOrm:
        row = await self.session.get(ReportFigureOrm, figure_id)
        if row is None:
            raise AppError(404, "NOT_FOUND", "这张图不存在")
        return row

    async def _expire(self, row: ReportFigureOrm) -> None:
        if row.status != "running" or now_ms() - row.updated_at <= _STALE_MS:
            return
        where = (row.step or "计算").strip()
        message = f"停在「{where}」，超过 3 分钟没有继续"
        row.status = "failed"
        row.error = message
        row.step = message
        await self.session.commit()


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


def _execute(figure_id: str, records: list[dict], samples: list[dict], code: str) -> tuple[dict, Path | None, str]:
    root = _sandbox_temp_dir(figure_id)
    work = root / "work"
    out = root / "out"
    work.mkdir()
    out.mkdir()
    try:
        body = json.dumps(records, ensure_ascii=False)
        (work / "results.json").write_text(body, encoding="utf-8")
        (work / "runs.json").write_text(body, encoding="utf-8")
        (work / "samples.json").write_text(json.dumps(samples, ensure_ascii=False), encoding="utf-8")
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
    table = _data_table(result.get("table"))
    if table:
        stored["table"] = table
    row.echarts_option = stored if panels or summary or table else None
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
        "run_id": row.run_id,
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
    table = stored.get("table") if isinstance(stored.get("table"), dict) else None
    questions = []
    for item in row.questions or []:
        if isinstance(item, dict) and item.get("text"):
            questions.append(FigureQuestionOut(text=str(item["text"]), options=[str(option) for option in item.get("options") or []]))
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
        table=FigureTableOut.model_validate(table) if table else None,
        questions=questions,
        note=row.note or "",
        usage=ReportUsageOut(input=row.input_tokens, output=row.output_tokens),
        error=row.error or None,
        step=row.step,
    )


def _remember_ask(row: ReportFigureOrm, payload: dict) -> None:
    questions = payload.get("questions") or []
    note = str(payload.get("note") or "")
    if payload.get("kind") == "gap" or int(row.ask_round or 0) >= 3:
        row.questions = []
        row.note = note or "；".join(str(item.get("text") or "") for item in questions if isinstance(item, dict))
        row.note = (row.note or "还缺画出这张图的信息")[:300]
    else:
        row.ask_round = int(row.ask_round or 0) + 1
        row.questions = questions
        row.note = _hint_text(payload)
    row.status = "asking"
    row.step = "还要补充"


def _hint_text(payload: dict) -> str:
    hint = payload.get("hint") if isinstance(payload.get("hint"), dict) else {}
    need = str(hint.get("need") or "").strip()
    allow = str(hint.get("allow") or "").strip()
    if not need:
        return ""
    text = f"至少还要：{need}"
    if allow:
        text += f"。可以自己规定：{allow}"
    return text[:300]


def _reply_text(text: str, picks: list[str]) -> str:
    chosen = [item.strip() for item in picks if item and item.strip()]
    typed = text.strip()
    parts = []
    if chosen:
        parts.append("选择：" + "、".join(chosen))
    if typed:
        parts.append(typed)
    return "\n".join(parts)


def _needs_process(columns: list[str], full_curve: bool) -> bool:
    if full_curve:
        return True
    return any(column in PROCESS_COLUMNS for column in columns)


def _data_table(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    columns = [str(item)[:40] for item in raw.get("columns") or [] if str(item).strip()]
    rows = []
    for item in (raw.get("rows") or [])[:40]:
        if isinstance(item, list):
            rows.append([str(cell)[:80] for cell in item[: len(columns) or 8]])
    if not columns and not rows:
        return None
    name = str(raw.get("name") or "").strip()[:40] or "所用数据"
    return {"name": name, "columns": columns, "rows": rows}


async def _request_turn(row: ReportFigureOrm, catalog: str, failure: str, model: str | None = None) -> tuple[dict, int, int, str]:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    model = (model or settings.anthropic_model or "deepseek-flash").strip()
    history = []
    for item in row.thread or []:
        if isinstance(item, dict) and item.get("content"):
            who = "用户" if item.get("role") == "user" else "你"
            history.append(f"{who}：{item['content']}")
    content = f"{_PROMPT}\n目录：\n{catalog}\n用户要求：{row.prompt}"
    if history:
        content += "\n已有对话：\n" + "\n".join(history)
    if int(row.ask_round or 0) >= 3:
        content += "\n三轮问题已经问完，用户也答完了。这一轮必须写 code 出图，不要 questions。没问到的按用户已经说过的做，用户没说过的用目录里的限值和分组。超过 200 条时只使用其中前 200 条，并在标题写明。"
    if failure:
        content += f"\n上次没有成功，错误是：{failure[-1500:]}\n请重写。"
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
            raise AppError(502, "AGENT_FAILED", "模型没有返回分析结果") from exc
        input_tokens += int(usage.get("prompt_tokens") or 0)
        output_tokens += int(usage.get("completion_tokens") or 0)
        model_name = str(data.get("model") or model)
        if isinstance(text, str) and text.strip():
            break
    if not isinstance(text, str) or not text.strip():
        raise AppError(502, "AGENT_FAILED", "模型没有返回分析结果")
    try:
        payload = parse_model_payload(text)
    except ValueError as exc:
        raise AppError(502, "AGENT_FAILED", "模型没有返回分析结果") from exc
    if payload["kind"] == "ask":
        thread = list(row.thread or [])
        thread.append({"role": "assistant", "content": "；".join(item["text"] for item in payload["questions"])})
        row.thread = thread
    return payload, input_tokens, output_tokens, model_name


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
