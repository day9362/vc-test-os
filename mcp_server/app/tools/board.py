from typing import Literal

from app.tools.data import vc_data
from app.tools.operate import run_operate

BoardAction = Literal[
    "boards",
    "board",
    "batches",
    "batch",
    "models",
    "defect_kinds",
    "create_batch",
    "requeue",
]
BoardState = Literal["NEW", "IN_MACHINE", "TESTED"]
BatchState = Literal["running", "done", "stopped"]

_READ = {"boards", "board", "batches", "batch", "models", "defect_kinds"}


async def vc_board(
    action: BoardAction,
    model: str | None = None,
    batch_id: str | None = None,
    serial_number: str | None = None,
    board_state: BoardState | None = None,
    golden: bool | None = None,
    state: BatchState | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    count: int | None = None,
    defect_ratio: float | None = None,
    batch_factor: float | None = None,
    yield_rate: float | None = None,
    yield_random: bool | None = None,
    yield_min: float | None = None,
    yield_max: float | None = None,
    count_random: bool | None = None,
    count_min: int | None = None,
    count_max: int | None = None,
    confirm_id: str | None = None,
    approval: str | None = None,
) -> dict:
    """VC-TestOS 板子和批次。查询、拉新、放回待测都是这个工具的 action。

    action:
    - boards：按 model、batch_id、board_state（NEW 待测、IN_MACHINE 在机、TESTED 已测完）、golden 查板。没有等级、单板缺陷和真实热阻。
    - board：按 serial_number 看一片板，字段同上。
    - batches：批次统计，可按 model、state（running/done/stopped）、q 筛选。这里的缺陷比例是建批设定，不是测试良率。
    - batch：一个批次的统计，要 batch_id。
    - models：型号目录和参考功率。
    - defect_kinds：缺陷种类和现象。这是目录，不能据此判断某一片板有没有缺陷。
    - create_batch：拉新，生成一批待测板，要 model。片数用 count，或 count_random 配 count_min、count_max。良率用 yield_rate（0 到 1，1 表示没有次品），或 yield_random 配 yield_min、yield_max；也可以直接给 defect_ratio。序列号由平台分配。需批准。
    - requeue：把已测完的标准样品 serial_number 放回待测。普通板会被拒绝。需批准。
    confirm_id、approval 只由页面批准后使用，不要自己填写。
    """
    if action in _READ:
        return await vc_data(
            action,
            model=model,
            batch_id=batch_id,
            serial_number=serial_number,
            board_state=board_state,
            golden=golden,
            state=state,
            q=q,
            cursor=cursor,
            limit=limit,
        )
    return await run_operate(
        action,
        model=model,
        count=count,
        defect_ratio=defect_ratio,
        batch_factor=batch_factor,
        yield_rate=yield_rate,
        yield_random=yield_random,
        yield_min=yield_min,
        yield_max=yield_max,
        count_random=count_random,
        count_min=count_min,
        count_max=count_max,
        serial_number=serial_number,
        confirm_id=confirm_id,
        approval=approval,
        tool="vc_board",
    )
