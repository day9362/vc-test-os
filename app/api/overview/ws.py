import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import SessionLocal
from app.core.redis import redis_client
from app.repo.user_repo import UserRepo
from app.service.auth_service import AuthService
from app.service.overview.hub import hub

router = APIRouter(tags=["overview"])


@router.websocket("/ws")
async def overview_ws(socket: WebSocket, token: str = "") -> None:
    await socket.accept()
    async with SessionLocal() as session:
        try:
            await AuthService(UserRepo(session), redis_client()).current_user(token)
        except Exception:
            await socket.close(code=4401)
            return
    hub.register(socket)

    async def ping() -> None:
        while True:
            await asyncio.sleep(15)
            await socket.send_json({"topic": "ping"})

    task = asyncio.create_task(ping())
    try:
        while True:
            raw = await socket.receive_text()
            message = json.loads(raw)
            if message.get("op") == "subscribe":
                hub.subscribe(socket, list(message.get("topics") or []))
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        hub.disconnect(socket)
