from dataclasses import dataclass
from typing import Any

from app.backend import Backend, Reply
from app.identity import Identity, current_identity

_backend: Backend | None = None
_store: Any = None


def set_backend(backend: Backend | None) -> None:
    global _backend
    _backend = backend


def set_store(store: Any) -> None:
    global _store
    _store = store


def get_store() -> Any:
    if _store is None:
        raise RuntimeError("approval store is not ready")
    return _store


@dataclass
class Ctx:
    backend: Backend
    identity: Identity

    async def get(self, path: str, params: dict | None = None, timeout: float | None = None) -> Reply:
        return await self.backend.get(self.identity, path, params, timeout)

    async def post(self, path: str, json=None, idem: str | None = None, timeout: float | None = None) -> Reply:
        return await self.backend.post(self.identity, path, json, idem, timeout)

    async def put(self, path: str, json=None, idem: str | None = None) -> Reply:
        return await self.backend.put(self.identity, path, json, idem)

    async def delete(self, path: str, idem: str | None = None) -> Reply:
        return await self.backend.delete(self.identity, path, idem)


def ctx() -> Ctx:
    if _backend is None:
        raise RuntimeError("backend client is not ready")
    return Ctx(_backend, current_identity())
