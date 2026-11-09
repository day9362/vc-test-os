from app.core.clock import now_ms

HOLD_MS = 2000
_until: dict[str, int] = {}


def hold_machine(machine_id: str, ms: int = HOLD_MS) -> None:
    """本地指令刚写完时，短时间内不用集群的旧槽位把这次结果盖掉。"""
    _until[machine_id] = now_ms() + ms


def machine_held(machine_id: str) -> bool:
    return now_ms() < _until.get(machine_id, 0)
