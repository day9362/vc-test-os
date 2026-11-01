from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repo.settings_repo import SettingsRepo
from app.service.ai.catalog import MODULE_IDS

MODEL_CHOICES = ("deepseek-flash", "deepseek-v3", "qwen3-max")


def fallback_model() -> str:
    return (settings.anthropic_model or "deepseek-flash").strip() or "deepseek-flash"


def shared_model(ai: dict | None) -> str:
    chosen = str((ai or {}).get("model") or "").strip()
    return chosen or fallback_model()


def apply_shared_model(ai: dict) -> dict:
    chosen = shared_model(ai)
    ai["model"] = chosen
    models = {str(key): str(value) for key, value in (ai.get("models") or {}).items() if value}
    for module_id in MODULE_IDS:
        models[module_id] = chosen
    ai["models"] = models
    return ai


async def configured_model(session: AsyncSession) -> str:
    row = await SettingsRepo(session).get_or_create()
    return shared_model((row.payload or {}).get("ai"))
