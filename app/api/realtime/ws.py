import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.database import SessionLocal
from app.core.redis import redis_client
from app.models.dto.realtime import SubscribeIn
from app.repo.user_repo import UserRepo
from app.service.auth_service import AuthService
from app.service.realtime.hub import hub

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def realtime_ws(socket: WebSocket, token: str = "") -> None:
    await socket.accept()
    async with SessionLocal() as session:
        try:
            await AuthService(UserRepo(session), redis_client()).current_user(token)
        except Exception:
            await socket.close(code=4401)
            return
    hub.register(socket)
    heartbeat = asyncio.create_task(_heartbeat(socket))
    try:
        while True:
            raw = await socket.receive_text()
            try:
                message = SubscribeIn.model_validate_json(raw)
            except ValidationError:
                continue
            if message.op == "subscribe":
                hub.subscribe(socket, message.topics)
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
        hub.disconnect(socket)


async def _heartbeat(socket: WebSocket) -> None:
    while True:
        await asyncio.sleep(15)
        try:
            await socket.send_json({"topic": "ping"})
        except Exception:
            return
