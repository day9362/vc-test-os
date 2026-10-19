from pathlib import Path
from uuid import uuid4

from app.core.config import settings


def reports_dir() -> Path:
    path = Path(settings.reports_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_report_pdf(content: bytes) -> str:
    file_id = uuid4().hex
    name = f"{file_id}.pdf"
    (reports_dir() / name).write_bytes(content)
    return f"/files/reports/{name}"
