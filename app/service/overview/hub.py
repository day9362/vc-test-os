"""兼容旧调用。实时推送统一走 service.realtime。"""

from app.service.realtime.hub import hub

__all__ = ["hub"]
