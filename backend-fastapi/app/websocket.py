"""
app/websocket.py — WS /ws/live broadcast events
PRD F1.2 websocket
"""
from __future__ import annotations
import asyncio
import logging
import json
from fastapi import WebSocket
from collections import defaultdict

log = logging.getLogger("tkm.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.active.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self.lock:
            if ws in self.active:
                self.active.remove(ws)

    async def broadcast(self, message: dict) -> None:
        text = json.dumps(message, default=str)
        dead: list[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()
