from typing import Literal

from app.models import ChannelValue
from app.result import bad
from app.tools.data import vc_data
from app.tools.line import Window, vc_line
from app.tools.operate import run_operate
from app.tools.plan import run_plan
from app.tools.quality import run_quality

MachineAction = Literal[
    "overview",
    "machines",
    "machine",
    "slot",
    "production",
    "search",
    "sim_catalog",
    "calibration",
    "calibration_history",
    "plan_history",
    "audit",
    "power_on",
    "power_off",
    "reset",
    "maintenance",
    "slot_load",
    "slot_start",
    "slot_test",
    "slot_abort",
    "slot_clear_error",
    "dispatch",
    "production_precheck",
    "production_start",
    "production_stop",
    "sim_speed",
    "sim_scenario",
    "sim_fault",
    "suggest_compensation",
    "apply_compensation",
]

_LINE = {"overview", "machines", "machine", "slot", "production", "search"}
_CATALOG = {"sim_catalog", "calibration", "calibration_history", "plan_history", "audit"}
_COMPENSATION = {"suggest_compensation", "apply_compensation"}


async def vc_machine(
    action: MachineAction,
    machine_id: str | None = None,
    machine_ids: list[str] | None = None,
    slot_index: int | None = None,
    serial_number: str | None = None,
    serial_numbers: list[str] | None = None,
    status: str | None = None,
    comm: str | None = None,
    q: str | None = None,
    window: Window = "8h",
    detail: bool = False,
    loaded: bool = False,
    cursor: str | None = None,
    limit: int = 20,
    on: bool | None = None,
    plan_id: str | None = None,
    version: int | None = None,
    plan_version: int | None = None,
    batch_id: str | None = None,
    auto_recover: bool | None = None,
    max_count: int | None = None,
    speed: float | None = None,
    name: str | None = None,
    kind: str | None = None,
    mode: Literal["add", "set"] | None = None,
    items: list[ChannelValue] | None = None,
    channel: str | None = None,
    proposed_delta: float | None = None,
    unit: str | None = None,
    reason: str | None = None,
    method: str | None = None,
    evidence_run_ids: list[str] | None = None,
    suggestion_id: str | None = None,
    confirmed_delta: float | None = None,
    confirm_id: str | None = None,
    approval: str | None = None,
) -> dict:
    """VC-TestOS 机台。查询和操作都用这个工具，用 action 区分。启停、上方案、仿真、补偿都是 action，不是独立工具。

    查询：
    - overview：全线概况。window 取 1h/2h 时统计近 2 小时，其余为本班 8 小时。
    - machines：机台列表。可用 status、comm 筛选。
    - machine：一台的详情和槽位，要 machine_id。detail=true 返回完整字段。loaded=true 再读集群上现在装的方案，没装也算成功。
    - slot：一个槽，要 machine_id、slot_index（从 1 开始）。detail=true 附带过程曲线。
    - production：当前连续生产。
    - search：按关键字 q 找机台、批次、方案和测试记录。
    - sim_catalog：仿真场景和故障种类。用户明确要求切场景或注入故障时才查。
    - calibration / calibration_history：通道补偿现状和修改历史，要 machine_id。
    - plan_history：这台机用过的方案版本，要 machine_id。
    - audit：操作审计，可按 machine_id 筛选。
    操作（production_precheck 和 suggest_compensation 直接执行，其余中高风险返回 APPROVAL_REQUIRED）：
    - power_on / power_off / reset / maintenance：除 reset 外必须给 machine_ids。reset 不给 machine_ids 表示全部在线机台。maintenance 用 on=true 进入、false 退出。
    - slot_load / slot_start / slot_test / slot_abort / slot_clear_error：单槽，slot_index 从 1 开始。slot_load 和 slot_test 要 serial_number。
    - dispatch：上方案。把已发布的 plan_id 和 version 装到 machine_ids，不开始测试。
    - production_precheck：只检查，参数同 production_start。
    - production_start：开始连续生产，要 machine_ids、plan_id、plan_version，batch_id 和 serial_numbers 二选一。可给 auto_recover、max_count。auto_recover 不填表示故障时停住。
    - production_stop：停止连续生产。不给 batch_id 时停止当前生产。
    - sim_speed：改仿真倍率，必须给 machine_ids 和 speed。
    - sim_scenario / sim_fault：只在用户明确要求时用，先查 sim_catalog。sim_scenario 要 machine_id 和 name。sim_fault 要 machine_id 和 kind，可给 slot_index。
    - suggest_compensation：提交补偿建议，要 machine_id、channel、proposed_delta。不改读数。
    - apply_compensation：写入补偿。mode=add 在当前值上叠加，set 直接设为该值。可给 items，或 suggestion_id 加 confirmed_delta。只影响之后的新测试。
    建批次和放回待测用 vc_board。方案的起草和发布用 vc_plan。告警用 vc_alarm。报告用 vc_report。测试记录用 vc_run。
    读数里 99999 和 9999 表示接触不良，-1 表示采集无应答，-2 表示回答无法解析。开测后用 vc_run 看进度，不要等测试结束。
    confirm_id、approval 只由页面批准后使用，不要自己填写。
    """
    if action in {"create_batch", "requeue"}:
        return bad("建批次和放回待测用 vc_board。")
    if action in _LINE:
        return await vc_line(
            action,
            machine_id=machine_id,
            slot_index=slot_index,
            status=status,
            comm=comm,
            q=q,
            window=window,
            detail=detail,
            cursor=cursor,
            limit=limit,
            loaded=loaded,
        )
    if action in _CATALOG:
        return await vc_data(
            action,
            machine_id=machine_id,
            cursor=cursor,
            limit=limit,
        )
    if action == "dispatch":
        return await run_plan(
            "dispatch",
            plan_id=plan_id,
            version=version,
            machine_ids=machine_ids,
            confirm_id=confirm_id,
            approval=approval,
            tool="vc_machine",
        )
    if action in _COMPENSATION:
        return await run_quality(
            action,
            machine_id=machine_id,
            mode=mode,
            items=items,
            channel=channel,
            proposed_delta=proposed_delta,
            unit=unit,
            reason=reason,
            method=method,
            evidence_run_ids=evidence_run_ids,
            suggestion_id=suggestion_id,
            confirmed_delta=confirmed_delta,
            confirm_id=confirm_id,
            approval=approval,
            tool="vc_machine",
        )
    return await run_operate(
        action,
        machine_ids=machine_ids,
        machine_id=machine_id,
        slot_index=slot_index,
        serial_number=serial_number,
        on=on,
        plan_id=plan_id,
        plan_version=plan_version,
        batch_id=batch_id,
        serial_numbers=serial_numbers,
        auto_recover=auto_recover,
        max_count=max_count,
        speed=speed,
        name=name,
        kind=kind,
        confirm_id=confirm_id,
        approval=approval,
        tool="vc_machine",
    )
