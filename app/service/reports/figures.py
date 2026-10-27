import asyncio
import json
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
from app.models.dto.report import FigureCreatedOut, FigureOut, ReportUsageOut
from app.models.entity.user import UserEntity
from app.models.orm.alarm import AiCallOrm
from app.models.orm.report_figure import ReportFigureOrm
from app.models.orm.run import RunOrm
from app.repo.run_repo import RunRepo
from app.service.reports.narrative import chat_completions_url
from app.service.reports.sandbox import read_result, reject_code, run_in_sandbox, sanitize_option
from app.service.reports.store import reports_dir
from app.service.runs.cluster_ingest import fleet_machine_ids
from app.service.runs.run_service import RunService

_PROMPT = """你是批次报告的分析员。用户给了一句要求，你只写一段 Python。
数据在 DataFrame runs 里，列是 batch_id、machine_id、slot_index、serial_number、status、passed、fail_items、rc、dt01、ended_at。
定义函数 analyze(runs)，返回 dict，包含 title、echarts_option、results。
echarts_option 是 ECharts 的 option，只能是数据，不能有函数。results 是若干 ["名称", "值"]。
需要图片时用 matplotlib 保存到 /out/figure.png。
不要使用 os、subprocess、socket，不要联网。
返回 json，code 是 Python 源码，title 是短标题。代码尽量短，直接给结果，不要长篇说明。
"""


def batch_key(batch_ids: list[str]) -> str:
    return ",".join(sorted({item.strip() for item in batch_ids if item and item.strip()}))


class FigureService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, batch_ids: list[str], prompt: str, user: UserEntity) -> FigureCreatedOut:
        ids = [item.strip() for item in batch_ids if item and item.strip()]
        text = prompt.strip()
        if not ids:
            raise AppError(400, "BAD_REQUEST", "batch_ids 不能为空")
        if not text:
            raise AppError(400, "BAD_REQUEST", "分析要求不能为空")
        if len(text) > 200:
            raise AppError(400, "BAD_REQUEST", "分析要求不能超过 200 字")
        stamp = now_ms()
        row = ReportFigureOrm(
            figure_id=f"fig_{uuid4().hex[:8]}",
            batch_key=batch_key(ids),
            batch_ids=ids,
            prompt=text,
            status="running",
            step="正在准备数据",
            created_at=stamp,
            updated_at=stamp,
            model=settings.anthropic_model or "deepseek-flash",
        )
        self.session.add(row)
        await self.session.commit()
        return FigureCreatedOut(figure_id=row.figure_id)

    async def get(self, figure_id: str) -> FigureOut:
        row = await self._row(figure_id)
        await self._expire(row)
        return _out(row)

    async def list_for(self, batch_ids: str) -> list[FigureOut]:
        key = batch_key(batch_ids.split(","))
        if not key:
            return []
        rows = (await self.session.scalars(select(ReportFigureOrm).where(ReportFigureOrm.batch_key == key).order_by(ReportFigureOrm.created_at))).all()
        for row in rows:
            await self._expire(row)
        return [_out(row) for row in rows]

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
        try:
            records = await self._records(row.batch_ids)
            if not records:
                raise AppError(400, "BAD_REQUEST", "所选批次还没有测完的片子")
            await self._step(row, "正在让模型写分析代码")
            code, title, input_tokens, output_tokens, model_name = await _request_code(row.prompt, records, "")
            blocked = reject_code(code)
            if blocked:
                code, title, extra_in, extra_out, model_name = await _request_code(row.prompt, records, blocked)
                input_tokens += extra_in
                output_tokens += extra_out
                blocked = reject_code(code)
            if blocked:
                raise AppError(502, "AGENT_FAILED", blocked)
            row.code = code
            row.title = title
            await self._step(row, "在沙箱执行 Python")
            result, png, failure = await asyncio.to_thread(_execute, row.figure_id, records, code)
            if failure:
                await self._step(row, "代码执行失败，正在重写")
                code, title, extra_in, extra_out, model_name = await _request_code(row.prompt, records, failure)
                input_tokens += extra_in
                output_tokens += extra_out
                if reject_code(code):
                    raise AppError(502, "AGENT_FAILED", "重写后的代码仍然不能执行")
                row.code = code
                row.title = title or row.title
                await self._step(row, "在沙箱执行 Python")
                result, png, failure = await asyncio.to_thread(_execute, row.figure_id, records, code)
            if failure:
                raise AppError(502, "AGENT_FAILED", "沙箱没有算出结果")
            await self._step(row, "正在读取结果")
            _apply_result(row, result, png)
        except AppError as exc:
            error = exc.message
        except Exception:
            error = "分析没有完成"
        row.model = model_name
        row.input_tokens = input_tokens
        row.output_tokens = output_tokens
        row.updated_at = now_ms()
        if error:
            row.status = "failed"
            row.error = error
            row.step = "分析没有完成"
        else:
            row.status = "done"
            row.error = ""
            row.step = "done"
        self.session.add(AiCallOrm(
            id=f"call-{uuid4().hex[:8]}",
            time=now_ms(),
            module="report",
            user=user_name,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=max(now_ms() - row.created_at, 1),
            ok=not error,
            ref={"figure_id": figure_id, "batch_ids": row.batch_ids},
        ))
        await self.session.commit()

    async def _records(self, batch_ids: list[str]) -> list[dict]:
        runs = RunService(self.session)
        await runs._ensure_fleet()
        rows = await RunRepo(self.session).list_by_batches(batch_ids, fleet_machine_ids() or None)
        return [_record(row) for row in rows[:5000]]

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


async def execute_figure(figure_id: str, user_name: str) -> None:
    async with SessionLocal() as session:
        await FigureService(session).run(figure_id, user_name)


def _execute(figure_id: str, records: list[dict], code: str) -> tuple[dict, Path | None, str]:
    root = Path(tempfile.mkdtemp(prefix=f"vcos-{figure_id}-"))
    work = root / "work"
    out = root / "out"
    work.mkdir()
    out.mkdir()
    try:
        (work / "runs.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
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


def _apply_result(row: ReportFigureOrm, result: dict, png: Path | None) -> None:
    title = str(result.get("title") or row.title or row.prompt)[:40]
    option = result.get("echarts_option")
    cleaned = sanitize_option(option) if option else None
    results = []
    raw = result.get("results")
    if isinstance(raw, list):
        for item in raw[:12]:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                results.append([str(item[0])[:40], str(item[1])[:80]])
    if cleaned is None and png is None:
        raise AppError(502, "AGENT_FAILED", "没有生成图表")
    row.title = title
    row.echarts_option = cleaned
    row.results = results
    row.png_name = png.name if png else ""


def _record(row: RunOrm) -> dict:
    return {
        "batch_id": row.batch_id,
        "machine_id": row.machine_id,
        "slot_index": row.slot_index,
        "serial_number": row.serial_number,
        "status": row.status,
        "passed": row.passed,
        "fail_items": "、".join(row.fail_items or []),
        "rc": row.rc,
        "dt01": row.dt01,
        "ended_at": row.ended_at,
    }


def _out(row: ReportFigureOrm) -> FigureOut:
    return FigureOut(
        figure_id=row.figure_id,
        status=row.status,
        prompt=row.prompt,
        title=row.title,
        echarts_option=row.echarts_option,
        png_url=f"/api/v1/reports/figures/{row.figure_id}.png" if row.png_name else None,
        code=row.code,
        results=row.results or [],
        usage=ReportUsageOut(input=row.input_tokens, output=row.output_tokens),
        error=row.error or None,
        step=row.step,
    )


async def _request_code(prompt: str, records: list[dict], failure: str) -> tuple[str, str, int, int, str]:
    if not settings.anthropic_base_url or not settings.anthropic_api_key:
        raise AppError(503, "MODEL_NOT_CONFIGURED", "没有配置第三方模型地址或密钥")
    model = settings.anthropic_model or "deepseek-flash"
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
