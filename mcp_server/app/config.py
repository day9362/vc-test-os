from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    vc_api_base: str = "http://127.0.0.1:8000/api/v1"
    vc_tenant: str = ""
    vc_username: str = ""
    vc_password: str = ""
    vc_timeout_s: float = 15
    vc_long_timeout_s: float = 90
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8100
    mcp_approval_secret: str = ""
    redis_url: str = "redis://127.0.0.1:6379/0"
    approval_ttl_s: int = 600


settings = Settings()
