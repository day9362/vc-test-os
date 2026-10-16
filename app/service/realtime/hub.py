import json

from fastapi import WebSocket

from app.core.clock import now_ms
from app.models.entity.realtime import TOPICS


class RealtimeHub:
    """只把新事件推给当前订阅者，不缓存历史。客户端重连后自己拉快照。"""

    def __init__(self) -> None:
        self.clients: list[tuple[WebSocket, set[str]]] = []

    def register(self, socket: WebSocket) -> None:
        self.clients.append((socket, set()))

    def subscribe(self, socket: WebSocket, topics: list[str]) -> list[str]:
        accepted = [topic for topic in topics if topic in TOPICS]
        for client, owned in self.clients:
            if client is socket:
                owned.clear()
                owned.update(accepted)
                break
        return accepted

    def disconnect(self, socket: WebSocket) -> None:
        self.clients = [(client, owned) for client, owned in self.clients if client is not socket]

    async def publish(self, topic: str, data) -> None:
        if topic not in TOPICS:
            return
        message = json.dumps({"topic": topic, "ts": now_ms(), "data": data}, ensure_ascii=False)
        dead: list[WebSocket] = []
        for client, owned in list(self.clients):
            if topic not in owned:
                continue
            try:
                await client.send_text(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self.disconnect(client)


hub = RealtimeHub()
