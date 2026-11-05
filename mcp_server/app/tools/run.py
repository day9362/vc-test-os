from typing import Literal

from app.tools.data import Metric, Window, vc_data

RunAction = Literal["runs", "run", "ground_truth", "compare", "trend", "export"]


async def vc_run(
    action: RunAction,
    run_id: str | None = None,
    batch_id: str | None = None,
    batch_ids: list[str] | None = None,
    machine_id: str | None = None,
    model: str | None = None,
    passed: bool | None = None,
    status: str | None = None,
    q: str | None = None,
    metric: Metric = "output",
    window: Window = "8h",
    from_ms: int | None = None,
    to_ms: int | None = None,
    detail: bool = False,
    cursor: str | None = None,
    limit: int = 20,
    since: float | None = None,
    limits_plan_id: str | None = None,
    version: int | None = None,
) -> dict:
    """VC-TestOS 测试记录。只查不改。良率只按测试记录算，不用批次的缺陷比例。

    action:
    - runs：测试记录列表。可按 machine_id、batch_id、passed、status（RUNNING/DONE/ABORTED）、q、时间（window 或 from_ms/to_ms）筛选。
    - run：一条记录的判定项和失败项，要 run_id。detail=true 附带采样。since 是已见过的最大 t_s，limit 是这次最多条数。续读时不要把 since 改小。
    - ground_truth：仿真真值，要 run_id。只在用户要核对物理答案时用。
    - compare：对比 2–5 个批次的良率、失败项分布、各机台良率。给 batch_ids；不给时用 model 取该型号最近 3 个批次。
    - trend：metric=output 产出与良率（按 5 分钟）、anomaly 异常分类趋势、rc_bias 各机台 Rc 偏差。
    - export：导出已完成且保留结果的生产 CSV，必填 limits_plan_id，可选 version。表头三行是列名、上限、下限。
    读数里 99999 和 9999 表示接触不良，-1 表示采集无应答，-2 表示回答无法解析。60 秒附近的快照不参与合格判定。
    """
    return await vc_data(
        action,
        run_id=run_id,
        batch_id=batch_id,
        batch_ids=batch_ids,
        machine_id=machine_id,
        model=model,
        passed=passed,
        status=status,
        q=q,
        metric=metric,
        window=window,
        from_ms=from_ms,
        to_ms=to_ms,
        detail=detail,
        cursor=cursor,
        limit=limit,
        since=since,
        limits_plan_id=limits_plan_id,
        version=version,
    )
