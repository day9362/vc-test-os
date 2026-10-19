from app.core.clock import now_ms

_runs: dict[str, dict] = {}


def record(key: str, elapsed_ms: int, failed: bool) -> None:
    _runs[key] = {
        "last_at": now_ms(),
        "elapsed_ms": max(int(elapsed_ms), 0),
        "failed": failed,
    }


def snapshot() -> dict[str, dict]:
    return dict(_runs)
