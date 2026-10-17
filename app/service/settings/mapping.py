from urllib.parse import urlsplit, urlunsplit

from app.models.dto.settings import PlatformSettingsOut
from app.models.entity.settings import (
    AiSettings,
    ClusterSettings,
    PlatformSettings,
    RuleSettings,
    SimSettings,
    StorageSettings,
    SyncJob,
)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith("sk-") and len(value) > 7:
        return f"sk-****{value[-4:]}"
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


def mask_dsn(dsn: str) -> str:
    parts = urlsplit(dsn)
    if not parts.username and not parts.password:
        return dsn
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    user = parts.username or ""
    password = mask_secret(parts.password) if parts.password else None
    netloc = f"{user}:{password}@{host}" if password else f"{user}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def settings_entity(payload: dict, updated_at: int) -> PlatformSettings:
    cluster = payload.get("cluster") or {}
    sim = payload.get("sim") or {}
    storage = payload.get("storage") or {}
    ai = payload.get("ai") or {}
    rules = payload.get("rules") or {}
    return PlatformSettings(
        source=payload.get("source") or "sim",
        cluster=ClusterSettings(
            base_url=cluster.get("base_url") or "",
            token=cluster.get("token") or "",
            timeout_s=cluster.get("timeout_s") or 5,
            retries=cluster.get("retries") or 0,
            on_503=cluster.get("on_503") or "skip",
        ),
        sim=SimSettings(
            base_url=sim.get("base_url") or "",
            speed=sim.get("speed") or 1,
            use_ground_truth=bool(sim.get("use_ground_truth")),
        ),
        jobs=[
            SyncJob(
                key=job.get("key") or "",
                name=job.get("name") or "",
                api=job.get("api") or "",
                interval_s=int(job.get("interval_s") or 0),
                enabled=bool(job.get("enabled")),
                note=job.get("note") or "",
            )
            for job in payload.get("jobs") or []
        ],
        storage=StorageSettings(
            dsn=storage.get("dsn") or "",
            samples_days=int(storage.get("samples_days") or 0),
            runs_days=int(storage.get("runs_days") or 0),
            agg_5m=bool(storage.get("agg_5m")),
            object_store=storage.get("object_store") or "",
        ),
        ai=AiSettings(
            base_url=ai.get("base_url") or "",
            api_key=ai.get("api_key") or "",
            monthly_budget_m=float(ai.get("monthly_budget_m") or 0),
            alert_pct=int(ai.get("alert_pct") or 0),
            models=dict(ai.get("models") or {}),
        ),
        rules=RuleSettings(
            drift_c=float(rules.get("drift_c") or 0),
            we_rules=list(rules.get("we_rules") or []),
            sentinel_as_data_anomaly=bool(rules.get("sentinel_as_data_anomaly")),
            degraded_alarm=bool(rules.get("degraded_alarm")),
            ack_timeout_min=int(rules.get("ack_timeout_min") or 0),
        ),
        updated_at=updated_at,
    )


def settings_out(entity: PlatformSettings) -> PlatformSettingsOut:
    return PlatformSettingsOut(
        source=entity.source,
        cluster=entity.cluster.__dict__ | {"token": mask_secret(entity.cluster.token)},
        sim=entity.sim.__dict__,
        jobs=[job.__dict__ for job in entity.jobs],
        storage=entity.storage.__dict__ | {"dsn": mask_dsn(entity.storage.dsn)},
        ai=entity.ai.__dict__ | {"api_key": mask_secret(entity.ai.api_key)},
        rules=entity.rules.__dict__,
    )
