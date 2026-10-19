from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://vcos:vcos@127.0.0.1:5432/vcos"
    redis_url: str = "redis://127.0.0.1:6379/0"
    jwt_secret: str = "vc-test-os-dev-secret"
    jwt_expire_minutes: int = 720
    cluster_base_url: str = ""
    cluster_token: str = ""
    cluster_timeout_s: float = 5
    degraded_alarm: bool = True
    drift_c: float = 0.15
    sentinel_as_data_anomaly: bool = True
    reports_dir: str = "data/reports"


settings = Settings()
