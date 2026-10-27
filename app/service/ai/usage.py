from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.errors import AppError
from app.models.dto.ai_usage import (
    AiCallOut,
    AiCallPageOut,
    AiModuleOut,
    UsageDayOut,
    UsageModuleOut,
    UsageMonthOut,
    UsageSummaryOut,
)
from app.models.orm.alarm import AiCallOrm, AlarmOrm
from app.repo.settings_repo import SettingsRepo
from app.service.ai.catalog import AUTO_MODULES, MODULES, MODULE_IDS, cost_cny
from app.service.settings.defaults import DEFAULT_AI_MODELS

DAY_MS = 86_400_000


def window_start(now: int, days: int) -> int:
    today = _day_start(now)
    return today - (days - 1) * DAY_MS


def month_start(now: int) -> int:
    current = datetime.fromtimestamp(now / 1000)
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


def should_alert(used: int, budget: int, alert_pct: int) -> bool:
    return budget > 0 and used * 100 >= budget * alert_pct


def over_budget(used: int, budget: int) -> bool:
    return budget > 0 and used >= budget


class UsageService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def modules(self) -> list[AiModuleOut]:
        chosen = await self._models()
        return [
            AiModuleOut(
                id=item["id"],
                name=item["name"],
                where=item["where"],
                desc=item["desc"],
                model=chosen.get(item["id"]) or item["model"],
                trigger=item["trigger"],
            )
            for item in MODULES
        ]

    async def summary(self, days: int) -> UsageSummaryOut:
        days = _days(days)
        now = now_ms()
        start = window_start(now, days)
        month = month_start(now)
        rows = await self._since(min(start, month))
        prices = await self._prices()
        chosen = await self._models()
        budget, alert_pct = await self._budget()
        window = [row for row in rows if row.time >= start]
        month_rows = [row for row in rows if row.time >= month]
        grouped: dict[str, list[AiCallOrm]] = {item["id"]: [] for item in MODULES}
        for row in window:
            grouped.setdefault(row.module, []).append(row)
        by_module = [_module_out(module_id, grouped.get(module_id, []), chosen, prices) for module_id in (item["id"] for item in MODULES)]
        for module_id, items in grouped.items():
            if module_id not in MODULE_IDS:
                by_module.append(_module_out(module_id, items, chosen, prices))
        incoming = sum(item.input for item in by_module)
        outgoing = sum(item.output for item in by_module)
        month_used = sum(row.input_tokens + row.output_tokens for row in month_rows)
        return UsageSummaryOut(
            days=days,
            total=incoming + outgoing,
            input=incoming,
            output=outgoing,
            calls=sum(item.calls for item in by_module),
            cost_cny=round(sum(item.cost_cny for item in by_module), 2),
            month=UsageMonthOut(
                used=month_used,
                budget=budget,
                alert_pct=alert_pct,
                paused=over_budget(month_used, budget),
            ),
            by_module=by_module,
        )

    async def daily(self, days: int) -> list[UsageDayOut]:
        days = _days(days)
        now = now_ms()
        start = window_start(now, days)
        buckets = {start + index * DAY_MS: {item["id"]: 0 for item in MODULES} for index in range(days)}
        for row in await self._since(start):
            bucket = _day_start(row.time)
            if bucket not in buckets:
                continue
            buckets[bucket][row.module] = buckets[bucket].get(row.module, 0) + row.input_tokens + row.output_tokens
        return [UsageDayOut(ts=ts, by_module=buckets[ts]) for ts in sorted(buckets)]

    async def calls(self, module: str | None, cursor: str | None, limit: int) -> AiCallPageOut:
        if limit < 1 or limit > 500:
            raise AppError(400, "BAD_REQUEST", "limit 需要在 1 到 500 之间")
        if module and module not in MODULE_IDS:
            raise AppError(400, "BAD_REQUEST", "未知的 AI 模块")
        if cursor and ":" not in cursor:
            raise AppError(400, "BAD_REQUEST", "cursor 格式不正确")
        stmt = select(AiCallOrm)
        if module:
            stmt = stmt.where(AiCallOrm.module == module)
        if cursor:
            mark_time, mark_id = cursor.split(":", 1)
            try:
                mark = int(mark_time)
            except ValueError as exc:
                raise AppError(400, "BAD_REQUEST", "cursor 格式不正确") from exc
            stmt = stmt.where((AiCallOrm.time < mark) | ((AiCallOrm.time == mark) & (AiCallOrm.id < mark_id)))
        rows = list((await self.session.execute(stmt.order_by(AiCallOrm.time.desc(), AiCallOrm.id.desc()).limit(limit + 1))).scalars().all())
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last.time}:{last.id}"
            rows = rows[:limit]
        return AiCallPageOut(items=[_call_out(row) for row in rows], next_cursor=next_cursor)

    async def record(
        self,
        *,
        module: str,
        user: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        ok: bool,
        ref: dict | None = None,
    ) -> None:
        self.session.add(AiCallOrm(
            id=f"call-{uuid4().hex[:8]}",
            time=now_ms(),
            module=module,
            user=user,
            model=model or "rule",
            input_tokens=max(int(input_tokens or 0), 0),
            output_tokens=max(int(output_tokens or 0), 0),
            latency_ms=max(int(latency_ms or 0), 0),
            ok=ok,
            ref=ref or {},
        ))
        await self.session.flush()
        await self._maybe_alert()

    async def auto_paused(self, module: str) -> bool:
        if module not in AUTO_MODULES:
            return False
        used, budget, _alert = await self._month_usage()
        return over_budget(used, budget)

    async def _maybe_alert(self) -> None:
        used, budget, alert_pct = await self._month_usage()
        if not should_alert(used, budget, alert_pct):
            return
        stamp = now_ms()
        alarm_id = f"AL-budget-{datetime.fromtimestamp(stamp / 1000):%Y%m}"
        if await self.session.get(AlarmOrm, alarm_id):
            return
        pct = round(used * 100 / budget)
        self.session.add(AlarmOrm(
            id=alarm_id,
            time=stamp,
            level="major" if over_budget(used, budget) else "minor",
            machine_id="",
            source="数据",
            code="AI_BUDGET",
            message=f"本月 AI Token 已用到预算的 {pct}%，自动归因会在用满后暂停",
            acked=False,
        ))

    async def _month_usage(self) -> tuple[int, int, int]:
        start = month_start(now_ms())
        used = sum(row.input_tokens + row.output_tokens for row in await self._since(start))
        budget, alert_pct = await self._budget()
        return used, budget, alert_pct

    async def _since(self, start: int) -> list[AiCallOrm]:
        stmt = select(AiCallOrm).where(AiCallOrm.time >= start)
        return list((await self.session.execute(stmt)).scalars().all())

    async def _payload(self) -> dict:
        row = await SettingsRepo(self.session).get_or_create()
        return row.payload or {}

    async def _budget(self) -> tuple[int, int]:
        ai = (await self._payload()).get("ai") or {}
        millions = float(ai.get("monthly_budget_m") or 0)
        return int(millions * 1_000_000), int(ai.get("alert_pct") or 80)

    async def _models(self) -> dict[str, str]:
        ai = (await self._payload()).get("ai") or {}
        models = dict(DEFAULT_AI_MODELS)
        models.update({str(key): str(value) for key, value in (ai.get("models") or {}).items() if value})
        return models

    async def _prices(self) -> dict:
        ai = (await self._payload()).get("ai") or {}
        raw = ai.get("prices")
        return raw if isinstance(raw, dict) else {}


def _module_out(module_id: str, rows: list[AiCallOrm], chosen: dict[str, str], prices: dict) -> UsageModuleOut:
    incoming = sum(row.input_tokens for row in rows)
    outgoing = sum(row.output_tokens for row in rows)
    totals: dict[str, int] = {}
    for row in rows:
        totals[row.model] = totals.get(row.model, 0) + row.input_tokens + row.output_tokens
    model = max(totals, key=totals.get) if totals else chosen.get(module_id, "")
    spent = sum(cost_cny(row.model, row.input_tokens, row.output_tokens, prices) for row in rows)
    return UsageModuleOut(
        module=module_id,
        model=model,
        calls=len(rows),
        input=incoming,
        output=outgoing,
        total=incoming + outgoing,
        cost_cny=round(spent, 2),
    )


def _call_out(row: AiCallOrm) -> AiCallOut:
    return AiCallOut(
        id=row.id,
        time=row.time,
        module=row.module,
        user=row.user,
        model=row.model,
        input=row.input_tokens,
        output=row.output_tokens,
        latency_ms=row.latency_ms,
        ok=row.ok,
        ref=row.ref or {},
    )


def _days(days: int) -> int:
    if days < 1 or days > 90:
        raise AppError(400, "BAD_REQUEST", "days 需要在 1 到 90 之间")
    return days


def _day_start(ts: int) -> int:
    current = datetime.fromtimestamp(ts / 1000)
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)
