from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.dto.report import AnalysisOut, AnalysisSliceOut, BatchCensusOut, FailGroupOut, FailParetoOut, LimitItemOut, ProcessNoteOut, SlotCensusOut
from app.models.orm.run import RunOrm, RunSampleOrm
from app.models.orm.test_plan import TestPlanOrm
from app.repo.run_repo import RunRepo
from app.service.reports.analysis_math import fail_groups, item_sort_key, process_shape, sample_series, summarize, usable
from app.service.machines.cluster import cluster_exchange
from app.service.runs.cluster_ingest import fleet_machine_ids
from app.service.runs.result_csv import _named_values, header_for
from app.service.runs.run_service import RunService


class AnalysisService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.runs = RunRepo(session)

    async def build(self, batch_ids: list[str]) -> AnalysisOut:
        analysis, _rows = await self.load(batch_ids)
        return analysis

    async def load(self, batch_ids: list[str]) -> tuple[AnalysisOut, list[dict]]:
        ids = [item.strip() for item in batch_ids if item and item.strip()]
        if not ids:
            raise AppError(400, "BAD_REQUEST", "batch_ids 不能为空")
        runs = RunService(self.session)
        await runs._ensure_fleet()
        rows = await self.runs.list_by_batches(ids, fleet_machine_ids() or None)
        limits = await self._limits(rows)
        observations, invalid_by_item, aborted, discarded, tallies = _observations(rows, limits)
        finished = sum(1 for row in rows if row.status == "COMPLETED" and row.keep_result)
        if not observations and aborted == 0 and discarded == 0:
            if finished and not limits:
                return _empty("这些批次已经测完，但这份方案的上下限没有取到"), []
            if finished:
                return _empty("这些批次已经测完，卡限项在结果里没有对应读数"), []
            return _empty("这些批次还没有测完的片子"), []
        if not limits:
            return _empty("这些批次的方案没有上下限，没有可分析的项"), []
        notes = await self._process(observations)
        overall = _slice("全部", observations, aborted, discarded, invalid_by_item)
        analysis = AnalysisOut(
            tested=len({row["run_id"] for row in observations}),
            aborted=aborted,
            discarded=discarded,
            invalid=sum(invalid_by_item.values()),
            fail_rank=_rank(overall.items),
            fail_groups=[FailGroupOut.model_validate(item) for item in fail_groups(observations)],
            overall=overall,
            batches=_groups(observations, "batch_id", tallies["batch"]),
            machines=_groups(observations, "machine_id", tallies["machine"]),
            slots=_groups(observations, "slot_name", tallies["slot"]),
            census=_census(observations),
            process=notes,
        )
        return analysis, observations

    async def _limits(self, rows: list[RunOrm]) -> dict[tuple[str, int], dict[str, tuple[str, float | None, float | None]]]:
        plan_ids = {row.plan_id for row in rows if row.plan_id}
        if not plan_ids:
            return {}
        found = await self.session.scalars(select(TestPlanOrm).where(TestPlanOrm.plan_id.in_(plan_ids)))
        limits: dict[tuple[str, int], dict[str, tuple[str, float | None, float | None]]] = {}
        for plan in found:
            spec = _with_ambient(_spec(plan.limits or []), plan.ambient_low_c, plan.ambient_high_c)
            if spec:
                limits[(plan.plan_id, int(plan.version))] = spec
        needed = {(row.plan_id, int(row.plan_version or 0)) for row in rows if row.plan_id}
        fetched: dict[str, dict] = {}
        for plan_id, version in sorted(needed - set(limits)):
            if plan_id not in fetched:
                fetched[plan_id] = await _cluster_plan(plan_id)
            raw = fetched[plan_id]
            if int(raw.get("version") or 0) != version:
                continue
            spec = _with_ambient(_spec(raw.get("limits") or []), raw.get("ambient_low_c"), raw.get("ambient_high_c"))
            if spec:
                limits[(plan_id, version)] = spec
        return limits

    async def _process(self, rows: list[dict]) -> list[ProcessNoteOut]:
        wanted: list[tuple[str, str, str, float | None, float | None]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if row["key"] not in ("temp_t0", "temp_t1", "temp_ambient", "power_w", "delta_t0_t1"):
                continue
            if not _is_fail(row):
                continue
            mark = (row["run_id"], row["item"])
            if mark in seen:
                continue
            seen.add(mark)
            wanted.append((row["run_id"], row["serial"], row["item"], row["low"], row["high"]))
            if len(wanted) >= 8:
                break
        if not wanted:
            return []
        samples = await self.session.scalars(select(RunSampleOrm).where(RunSampleOrm.run_id.in_({item[0] for item in wanted})))
        grouped: dict[str, list[dict]] = defaultdict(list)
        for point in samples:
            grouped[point.run_id].append({"t_s": point.t_s, "t0": point.t0, "t1": point.t1, "ta": point.ta, "power_w": point.power_w})
        notes = []
        key_by_item = {row["item"]: row["key"] for row in rows}
        for run_id, serial, item, low, high in wanted:
            shape = process_shape(sample_series(key_by_item.get(item, ""), grouped.get(run_id, [])), low, high)
            if shape:
                notes.append(ProcessNoteOut(serial_number=serial or run_id, item=item, shape=shape))
        return notes


def _observations(rows: list[RunOrm], limits: dict):
    observations = []
    invalid: dict[str, int] = defaultdict(int)
    tallies = {
        "batch": defaultdict(lambda: [0, 0]),
        "machine": defaultdict(lambda: [0, 0]),
        "slot": defaultdict(lambda: [0, 0]),
    }
    aborted = 0
    discarded = 0
    for row in rows:
        labels = {
            "batch": row.batch_id or "",
            "machine": row.machine_id or "",
            "slot": f"{row.machine_id}#{row.slot_index}",
        }
        if row.status != "COMPLETED":
            aborted += 1
            for kind, label in labels.items():
                tallies[kind][label][0] += 1
            continue
        if not row.keep_result:
            discarded += 1
            for kind, label in labels.items():
                tallies[kind][label][1] += 1
            continue
        spec = limits.get((row.plan_id, int(row.plan_version or 0))) or {}
        measured = _measured(row)
        for key, (name, low, high) in spec.items():
            raw = measured.get(key)
            if raw is None:
                continue
            if not usable(raw):
                invalid[name] += 1
                continue
            observations.append({
                "run_id": row.run_id,
                "serial": row.serial_number or "",
                "batch_id": row.batch_id or "",
                "machine_id": row.machine_id or "",
                "slot_name": f"{row.machine_id}#{row.slot_index}",
                "ended_at": int(row.ended_at or 0),
                "item": name,
                "key": key,
                "value": float(raw),
                "low": low,
                "high": high,
                "passed": row.passed is True,
            })
    return observations, invalid, aborted, discarded, tallies


def _measured(row: RunOrm) -> dict[str, float]:
    result = row.result if isinstance(row.result, dict) else {}
    found = _named_values(result.get("temps"))
    found.update(_named_values(result.get("forces")))
    found.update(_named_values(result.get("deltas")))
    if row.rc is not None and "thermal_resistance" not in found:
        found["thermal_resistance"] = float(row.rc)
    if row.dt01 is not None and "delta_t0_t1" not in found:
        found["delta_t0_t1"] = float(row.dt01)
    power = result.get("power_w")
    if isinstance(power, (int, float)) and "power_w" not in found:
        found["power_w"] = float(power)
    return found


def _slice(name: str, rows: list[dict], aborted: int, discarded: int, invalid: dict[str, int]) -> AnalysisSliceOut:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["item"]].append(row)
    items = [LimitItemOut.model_validate(summarize(item, values)) for item, values in grouped.items()]
    for item in items:
        item.invalid = invalid.get(item.item, 0)
    items.sort(key=lambda item: item_sort_key(item.item))
    return AnalysisSliceOut(
        name=name,
        aborted=aborted,
        discarded=discarded,
        invalid=sum(item.invalid for item in items),
        items=items,
        correlations=[],
        fail_groups=[FailGroupOut.model_validate(item) for item in fail_groups(rows)],
    )


def _groups(rows: list[dict], field: str, tally: dict) -> list[AnalysisSliceOut]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(field) or "")].append(row)
    names = set(grouped) | set(tally)
    slices = []
    for name in sorted(names):
        if not name:
            continue
        aborted, discarded = tally.get(name, (0, 0))
        slices.append(_slice(name, grouped.get(name, []), aborted, discarded, {}))
    return slices


def _slot_key(name: str) -> tuple[str, int]:
    machine, _, index = name.partition("#")
    try:
        return machine, int(index)
    except ValueError:
        return machine, 0


def _census(rows: list[dict]) -> list[BatchCensusOut]:
    wafers: dict[str, tuple[str, str, bool]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "")
        if run_id and run_id not in wafers:
            wafers[run_id] = (str(row.get("batch_id") or ""), str(row.get("slot_name") or ""), row.get("passed") is True)
    grouped: dict[str, dict[str, list[int]]] = {}
    order: list[str] = []
    for batch, slot, passed in wafers.values():
        if batch not in grouped:
            grouped[batch] = {}
            order.append(batch)
        cell = grouped[batch].setdefault(slot, [0, 0])
        cell[0] += 1
        if passed:
            cell[1] += 1
    found = []
    for batch in order:
        slots = [
            SlotCensusOut(slot=name, tested=counts[0], passed=counts[1])
            for name, counts in sorted(grouped[batch].items(), key=lambda item: _slot_key(item[0]))
            if name
        ]
        found.append(BatchCensusOut(batch=batch, tested=sum(item.tested for item in slots), passed=sum(item.passed for item in slots), slots=slots))
    return found


def _rank(items: list[LimitItemOut]) -> list[FailParetoOut]:
    ranked = [
        FailParetoOut(item=item.item, count=item.high_fail + item.low_fail)
        for item in items
        if item.high_fail or item.low_fail
    ]
    ranked.sort(key=lambda item: (-item.count, item_sort_key(item.item)))
    return ranked


def _is_fail(row: dict) -> bool:
    return (row["high"] is not None and row["value"] > row["high"]) or (row["low"] is not None and row["value"] < row["low"])


def _with_ambient(spec: dict, low: object, high: object) -> dict:
    low_value, high_value = _float(low), _float(high)
    if low_value is None and high_value is None:
        return spec
    spec = dict(spec)
    spec["temp_ambient"] = ("室温", low_value, high_value)
    return spec


def _spec(items: list) -> dict[str, tuple[str, float | None, float | None]]:
    spec: dict[str, tuple[str, float | None, float | None]] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("skipped"):
            continue
        name = str(item.get("item") or "")
        key = header_for(name)
        low, high = item.get("low"), item.get("high")
        if not key or not name or (low is None and high is None):
            continue
        spec[key] = (name, _float(low), _float(high))
    return spec


async def _cluster_plan(plan_id: str) -> dict:
    try:
        data = await cluster_exchange("GET", f"/plans/{plan_id}")
    except AppError:
        return {}
    if not isinstance(data, dict):
        return {}
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else data
    return plan if isinstance(plan, dict) else {}


def _float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _empty(note: str) -> AnalysisOut:
    return AnalysisOut(note=note, overall=AnalysisSliceOut(name="全部"))
