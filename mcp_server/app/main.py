from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.approval import MemoryStore, RedisStore
from app.backend import Backend
from app.config import settings
from app.identity import Identity
from app.server import build_mcp
from app.state import set_backend, set_store

mcp = build_mcp()
mcp_app = mcp.http_app(path="/")


async def _open_store():
    store = RedisStore(settings.redis_url)
    try:
        await store.put("mcp:ping", "1", 5)
        return store
    except Exception:
        await store.aclose()
        return MemoryStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    backend = Backend()
    store = await _open_store()
    set_backend(backend)
    set_store(store)
    app.state.backend = backend
    app.state.store = store
    try:
        async with mcp_app.lifespan(app):
            yield
    finally:
        await backend.aclose()
        await store.aclose()
        set_backend(None)
        set_store(None)


app = FastAPI(title="VC-TestOS MCP", lifespan=lifespan)


@app.middleware("http")
async def keep_mcp_path(request, call_next):
    # 有的客户端不跟随 /mcp → /mcp/ 的重定向。
    if request.scope.get("path") == "/mcp":
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"
    return await call_next(request)


app.mount("/mcp", mcp_app)


@app.get("/health")
async def health():
    reply = await app.state.backend.get(Identity(), "/sync/jobs/status", timeout=5)
    if reply.ok:
        backend = "reachable"
    elif reply.status == 401:
        backend = "reachable_unauthorized"
    else:
        backend = "unreachable"
    return {
        "service": "running",
        "backend": backend,
        "approval": "ready" if settings.mcp_approval_secret else "secret_missing",
        "store": "redis" if isinstance(app.state.store, RedisStore) else "memory",
    }


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
