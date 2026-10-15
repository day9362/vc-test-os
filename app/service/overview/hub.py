import json

from fastapi import WebSocket

from app.core.clock import now_ms


class OverviewHub:
    def __init__(self) -> None:
        self.clients: list[tuple[WebSocket, set[str]]] = []

    def register(self, socket: WebSocket) -> None:
        self.clients.append((socket, set()))

    def subscribe(self, socket: WebSocket, topics: list[str]) -> None:
        for client, owned in self.clients:
            if client is socket:
                owned.update(topics)

    def disconnect(self, socket: WebSocket) -> None:
        self.clients = [(client, owned) for client, owned in self.clients if client is not socket]

    async def publish(self, topic: str, data) -> None:
        message = json.dumps({"topic": topic, "ts": now_ms(), "data": data}, ensure_ascii=False)
        dead: list[WebSocket] = []
        for client, owned in self.clients:
            if topic not in owned:
                continue
            try:
                await client.send_text(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self.disconnect(client)


hub = OverviewHub()
