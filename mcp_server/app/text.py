import time

MACHINE_STATUS = {
    "CREATED": "未上电",
    "STARTING": "启动中",
    "READY": "就绪",
    "RUNNING": "测试中",
    "BUSY": "测试中",
    "FAULT": "故障",
    "MAINTENANCE": "维修中",
    "OFFLINE": "已关机",
    "STOPPED": "已停止",
}

COMM_STATUS = {"ONLINE": "通信正常", "DEGRADED": "通信降级", "DISCONNECTED": "通信断开"}

SLOT_PHASE = {
    "IDLE": "空闲",
    "LOADING": "装板中",
    "CLAMPING": "压紧中",
    "PREHEAT": "预热中",
    "RESET": "复位中",
    "SAMPLING": "测试中",
    "COMPLETED": "已测完",
    "ERROR": "出错",
}

BUSY_PHASES = {"LOADING", "CLAMPING", "PREHEAT", "RESET", "SAMPLING"}

WINDOW_HOURS = {"1h": 1, "2h": 2, "8h": 8, "24h": 24, "7d": 168}


def now_ms() -> int:
    return int(time.time() * 1000)


def window_range(window: str | None, from_ms: int | None = None, to_ms: int | None = None, default: str = "8h") -> tuple[int, int]:
    end = to_ms or now_ms()
    if from_ms:
        return from_ms, end
    hours = WINDOW_HOURS.get(window or default, WINDOW_HOURS[default])
    return end - hours * 3_600_000, end


def join_ids(ids: list[str] | None) -> str:
    items = [str(item) for item in ids or [] if item]
    return "、".join(items) if items else "（无）"


def status_text(status: str | None) -> str:
    return MACHINE_STATUS.get(str(status or ""), str(status or "状态未知"))


def phase_text(phase: str | None) -> str:
    return SLOT_PHASE.get(str(phase or ""), str(phase or "未知"))


def pct(passed: int, total: int) -> str:
    if total <= 0:
        return "—"
    return f"{passed / total * 100:.1f}%"


def clamp_limit(limit: int | None, default: int = 20) -> int:
    return max(1, min(int(limit or default), 200))
