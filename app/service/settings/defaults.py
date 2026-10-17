from app.core.config import settings

DEFAULT_JOBS = [
    {"key": "fleet", "name": "机群状态", "api": "GET /api/fleet", "interval_s": 2, "enabled": True, "note": "状态、通信、已装载方案、排队剩余"},
    {"key": "slots", "name": "槽位实时", "api": "GET /api/machines/{id}/slots", "interval_s": 1, "enabled": True, "note": "步骤、功率、真空、各测点温度；DISCONNECTED 时跳过"},
    {"key": "machine", "name": "机台详情", "api": "GET /api/machines/{id}", "interval_s": 10, "enabled": True, "note": "配置、报警、房间温度、能力范围"},
    {"key": "runs", "name": "测试记录", "api": "GET /api/runs", "interval_s": 5, "enabled": True, "note": "按 run_id 增量入库，RUNNING 记录持续跟踪"},
    {"key": "samples", "name": "过程曲线", "api": "GET /api/runs/{id}/samples?since=", "interval_s": 2, "enabled": True, "note": "用 seq 增量拉取，写入时序表"},
    {"key": "plans", "name": "测试方案", "api": "GET /api/plans", "interval_s": 60, "enabled": True, "note": "最新版本；历史版本按需拉取"},
    {"key": "batches", "name": "批次与型号", "api": "GET /api/products/batches", "interval_s": 300, "enabled": True, "note": "含 /api/product-models"},
    {"key": "calib", "name": "补偿与漂移", "api": "GET /api/machines/{id}/compensation · /drifts", "interval_s": 60, "enabled": True, "note": "用于设备一致性页"},
    {"key": "agg", "name": "5 分钟汇总", "api": "本地 · 连续聚合 agg_5m", "interval_s": 300, "enabled": True, "note": "良率、Rc 均值、异常数"},
]

DEFAULT_AI_MODELS = {
    "agent.analysis": "deepseek-v3",
    "agent.plan": "qwen3-max",
    "agent.ops": "qwen3-max",
    "report": "deepseek-v3",
    "anomaly": "deepseek-v3",
    "calib": "qwen3-max",
}


def default_payload() -> dict:
    return {
        "source": "sim",
        "cluster": {
            "base_url": settings.cluster_base_url or "http://10.20.1.10:18000/api",
            "token": settings.cluster_token or "",
            "timeout_s": settings.cluster_timeout_s,
            "retries": 2,
            "on_503": "skip",
        },
        "sim": {
            "base_url": "https://cluster.simuoss.cn/api",
            "speed": 1,
            "use_ground_truth": False,
        },
        "jobs": DEFAULT_JOBS,
        "storage": {
            "dsn": settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
            "samples_days": 400,
            "runs_days": 1095,
            "agg_5m": True,
            "object_store": "minio://127.0.0.1:9000/vcos",
        },
        "ai": {
            "base_url": "https://api.example.com/v1",
            "api_key": "",
            "monthly_budget_m": 120,
            "alert_pct": 80,
            "models": dict(DEFAULT_AI_MODELS),
        },
        "rules": {
            "drift_c": settings.drift_c,
            "we_rules": ["WE-1", "WE-2", "WE-4"],
            "sentinel_as_data_anomaly": True,
            "degraded_alarm": settings.degraded_alarm,
            "ack_timeout_min": 15,
        },
    }
