from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now_ms
from app.core.config import settings
from app.core.errors import AppError
from app.models.dto.stats import Agg5mOut, AnomalyTrendOut, KpiOut, KpiPrevOut, PipelineOut, PipelineStepOut, RcBiasItemOut, RcBiasOut
from app.models.entity.stats import PipelineStep
from app.repo.alarm_repo import AlarmRepo
from app.repo.machine_repo import MachineRepo
from app.repo.run_repo import RunRepo
from app.repo.stats_repo import StatsRepo
from app.service.runs.cluster_ingest import fleet_machine_ids, refresh_fleet

SHIFT_MS = 8 * 3_600_000
HOUR_MS = 3_600_000
SOURCE_CATEGORY = {"机台": "equipment", "槽位": "equipment", "漂移": "equipment", "判定": "product", "通信": "communication", "数据": "data"}


class StatsService:
    def __init__(self, session: AsyncSession):
        self.stats = StatsRepo(session)
        self.runs = RunRepo(session)
        self.alarms = AlarmRepo(session)
        self.machines = MachineRepo(session)

    async def kpi(self, range_name: str) -> KpiOut:
        if range_name not in {"shift", "2h"}:
            raise AppError(400, "BAD_REQUEST", "range 只能是 shift 或 2h")
        window = SHIFT_MS if range_name == "shift" else 2 * HOUR_MS
        end = now_ms()
        current = await self._window(end - window, end)
        previous = await self._window(end - 2 * window, end - window)
        fleet = await self._fleet_ids()
        allowed = set(fleet) if fleet else None
        rows = await self.machines.list_with_slots()
        if allowed:
            rows = [(machine, slots) for machine, slots in rows if machine.machine_id in allowed]
        online = 0
        busy = 0
        errors = 0
        slot_total = 0
        for machine, slots in rows:
            slot_total += machine.slot_count
            if machine.comm_status != "DISCONNECTED" and machine.status not in {"OFFLINE", "STOPPED"}:
                online += 1
            if machine.comm_status == "DISCONNECTED":
                continue
            busy += sum(1 for slot in slots if slot.phase not in {"IDLE", "ERROR", "COMPLETED"})
            errors += sum(1 for slot in slots if slot.phase == "ERROR")
        open_rows = await self.alarms.open_alarms()
        if allowed:
            open_rows = [alarm for alarm in open_rows if alarm.machine_id in allowed]
        rc_values = await self.runs.recent_rc(120, fleet)
        return KpiOut(
            online=online,
            total=len(rows),
            busy_slots=busy,
            error_slots=errors,
            slot_total=slot_total,
            tests=current[0],
            yield_rate=current[1],
            rc_mean=round(sum(rc_values) / len(rc_values), 3) if rc_values else 0,
            open_alarms=len(open_rows),
            critical_alarms=sum(1 for alarm in open_rows if alarm.level == "critical"),
            prev=KpiPrevOut(tests=previous[0], yield_rate=previous[1]),
        )

    async def agg5m(self, start: int | None, end: int | None) -> list[Agg5mOut]:
        end = now_ms() if end is None else end
        start = end - 8 * HOUR_MS if start is None else start
        return self._buckets(await self.runs.ended_between(start, end, await self._fleet_ids()), start, end)

    async def anomaly_trend(self, hours: int) -> AnomalyTrendOut:
        if hours < 1 or hours > 48:
            raise AppError(400, "BAD_REQUEST", "hours 需要在 1 到 48 之间")
        end = now_ms()
        start_hour = end - (end % HOUR_MS) - (hours - 1) * HOUR_MS
        marks = [start_hour + index * HOUR_MS for index in range(hours)]
        series = {name: [0] * hours for name in ("equipment", "product", "communication", "data")}
        fleet = await self._fleet_ids()
        allowed = set(fleet) if fleet else None
        for alarm in await self.alarms.since(start_hour):
            if allowed and alarm.machine_id not in allowed:
                continue
            category = SOURCE_CATEGORY.get(alarm.source)
            if category is None or alarm.time >= start_hour + hours * HOUR_MS:
                continue
            index = int((alarm.time - start_hour) // HOUR_MS)
            if 0 <= index < hours:
                series[category][index] += 1
        return AnomalyTrendOut(hours=marks, series=series)

    async def rc_bias(self) -> RcBiasOut:
        grouped = await self.runs.mean_rc_by_machine()
        fleet = await self._fleet_ids()
        if fleet:
            allowed = set(fleet)
            grouped = {machine_id: values for machine_id, values in grouped.items() if machine_id in allowed}
        means = []
        for machine_id in sorted(grouped):
            values = grouped[machine_id]
            if values:
                means.append((machine_id, sum(values) / len(values)))
        if not means:
            return RcBiasOut(median=0, items=[])
        ordered = sorted(value for _, value in means)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        return RcBiasOut(median=round(median, 3), items=[RcBiasItemOut(machine_id=machine_id, bias=round(value - median, 3)) for machine_id, value in means])

    async def pipeline(self) -> PipelineOut:
        fleet = await self._fleet_ids()
        allowed = set(fleet) if fleet else None
        rows = await self.machines.list_with_slots()
        if allowed:
            rows = [(machine, slots) for machine, slots in rows if machine.machine_id in allowed]
        loaded = sum(1 for machine, _slots in rows if machine.plan_id)
        disconnected = sum(1 for machine, _slots in rows if machine.comm_status == "DISCONNECTED")
        open_rows = await self.alarms.open_alarms()
        if allowed:
            open_rows = [alarm for alarm in open_rows if alarm.machine_id in allowed]
        critical = sum(1 for alarm in open_rows if alarm.level == "critical")
        steps = {
            "gen": PipelineStep("方案来自集群", "idle"),
            "check": PipelineStep("发布前校验在方案模块", "idle"),
            "dispatch": PipelineStep(f"{loaded} 台已装载方案", "ok" if loaded else "idle"),
            "collect": PipelineStep("同步正常" if disconnected == 0 else f"{disconnected} 台通信断开", "ok" if disconnected == 0 else "danger"),
            "anomaly": PipelineStep(f"{len(open_rows)} 条未确认", "danger" if critical else ("warn" if open_rows else "ok")),
            "calib": PipelineStep("补偿在设备配置", "idle"),
            "report": PipelineStep("按批次出报告", "idle"),
        }
        return PipelineOut(**{key: PipelineStepOut(text=step.text, state=step.state) for key, step in steps.items()})

    async def _fleet_ids(self) -> list[str] | None:
        if not settings.cluster_base_url:
            return None
        return fleet_machine_ids() or await refresh_fleet() or None

    def _buckets(self, rows, start: int, end: int) -> list[Agg5mOut]:
        step = 300_000
        first = start - (start % step)
        grouped: dict[int, list] = {}
        cursor = first
        while cursor < end:
            grouped[cursor] = []
            cursor += step
        for row in rows:
            key = row.ended_at - (row.ended_at % step)
            if key in grouped:
                grouped[key].append(row)
        out = []
        for bucket in sorted(grouped):
            group = grouped[bucket]
            tests = len(group)
            passed = sum(1 for item in group if item.passed is True)
            failed = sum(1 for item in group if item.passed is False and item.status == "COMPLETED")
            aborted = sum(1 for item in group if item.status in {"ABORTED", "FAULT"})
            rc_values = [item.rc for item in group if item.rc is not None]
            dt_values = [item.dt01 for item in group if item.dt01 is not None]
            out.append(Agg5mOut(
                bucket=bucket,
                tests=tests,
                passed=passed,
                failed=failed,
                aborted=aborted,
                rc_mean=round(sum(rc_values) / len(rc_values), 3) if rc_values else 0,
                dt01_mean=round(sum(dt_values) / len(dt_values), 3) if dt_values else 0,
            ))
        return out

    async def _window(self, start: int, end: int) -> tuple[int, float]:
        rows = await self.runs.ended_between(start, end, await self._fleet_ids())
        tests = len(rows)
        passed = sum(1 for row in rows if row.passed is True)
        rate = round(passed / tests * 100, 2) if tests else 0
        return tests, rate
