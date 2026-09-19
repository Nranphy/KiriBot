"""Gateway JSON WebSocket 传输抽象"""

import asyncio
import json
from abc import ABC, abstractmethod

from fastapi import WebSocket
from websockets.asyncio.client import ClientConnection, connect


class Connection(ABC):
    """串行发送和 JSON 对象收发契约"""

    def __init__(self, connection_name: str) -> None:
        self.connection_name = connection_name
        self.ready = False
        self.lock = asyncio.Lock()

    @abstractmethod
    async def open(self) -> None: ...

    @abstractmethod
    async def receive(self) -> dict: ...

    async def send(self, payload: dict) -> None:
        async with self.lock:
            await self._send(payload)

    @abstractmethod
    async def _send(self, payload: dict) -> None: ...

    @abstractmethod
    async def close(self, code: int = 1001) -> None: ...


class ForwardConnection(Connection, ABC):
    """Gateway 主动建立的 WebSocket 传输"""

    def __init__(self, connection_name: str, url: str) -> None:
        super().__init__(connection_name)
        self.url = url
        self.websocket: ClientConnection | None = None

    @abstractmethod
    def headers(self) -> dict[str, str]: ...

    async def open(self) -> None:
        self.websocket = await connect(self.url, additional_headers=self.headers(), open_timeout=10)

    async def receive(self) -> dict:
        if self.websocket is None:
            raise ConnectionError('连接未建立')
        payload = json.loads(await self.websocket.recv())
        if not isinstance(payload, dict):
            raise TypeError('协议消息必须是 JSON 对象')
        return payload

    async def _send(self, payload: dict) -> None:
        if self.websocket is None:
            raise ConnectionError('连接未建立')
        await self.websocket.send(json.dumps(payload))

    async def close(self, code: int = 1001) -> None:
        self.ready = False
        if self.websocket is not None:
            await self.websocket.close(code=code)
            self.websocket = None


class ReverseConnection(Connection, ABC):
    """Gateway 被动接受的 WebSocket 传输"""

    def __init__(self, connection_name: str, websocket: WebSocket) -> None:
        super().__init__(connection_name)
        self.websocket = websocket

    async def open(self) -> None:
        await self.websocket.accept()

    async def receive(self) -> dict:
        payload = await self.websocket.receive_json()
        if not isinstance(payload, dict):
            raise TypeError('协议消息必须是 JSON 对象')
        return payload

    async def _send(self, payload: dict) -> None:
        await self.websocket.send_json(payload)

    async def close(self, code: int = 1001) -> None:
        self.ready = False
        await self.websocket.close(code=code)
