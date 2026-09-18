"""Gateway 连接契约及主动、被动 WebSocket 的公共行为"""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from fastapi import WebSocket
from websockets.asyncio.client import ClientConnection, connect

if TYPE_CHECKING:
    from kiribot.services.gateway.gateway import Gateway


class Connection(ABC):
    """协议连接的生命周期、串行发送和消息处理契约"""

    def __init__(self, self_id: str) -> None:
        self.self_id = self_id
        self.ready = False
        self.lock = asyncio.Lock()

    @abstractmethod
    async def open(self) -> None:
        """建立或接受传输连接"""

    @abstractmethod
    async def receive(self) -> dict:
        """接收一个 JSON 对象"""

    async def send(self, payload: dict) -> None:
        """串行发送，避免多个请求同时写入连接"""
        async with self.lock:
            await self._send(payload)

    @abstractmethod
    async def _send(self, payload: dict) -> None:
        """写入底层传输"""

    @abstractmethod
    async def close(self, code: int = 1001) -> None:
        """关闭连接并撤销就绪状态"""

    @abstractmethod
    async def handshake(self) -> None:
        """完成协议握手后标记就绪"""

    @abstractmethod
    async def handle(self, gateway: Gateway, payload: dict) -> None:
        """执行协议特有的消息处理"""


class ForwardConnection(Connection, ABC):
    """主动建立 WS；重连由 Gateway 调度，不在连接中循环"""

    def __init__(self, self_id: str, url: str) -> None:
        super().__init__(self_id)
        self.url = url
        self.websocket: ClientConnection | None = None

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """提供协议握手请求头"""

    async def open(self) -> None:
        self.websocket = await connect(
            self.url, additional_headers=self.headers(), open_timeout=10
        )

    async def receive(self) -> dict:
        if self.websocket is None:
            raise ConnectionError("连接未建立")
        payload = json.loads(await self.websocket.recv())
        if not isinstance(payload, dict):
            raise TypeError("协议消息必须是 JSON 对象")
        return payload

    async def _send(self, payload: dict) -> None:
        if self.websocket is None:
            raise ConnectionError("连接未建立")
        await self.websocket.send(json.dumps(payload))

    async def close(self, code: int = 1001) -> None:
        self.ready = False
        if self.websocket is not None:
            await self.websocket.close(code=code)
            self.websocket = None


class ReverseConnection(Connection, ABC):
    """被动接受 WS，断开后由对端重新发起连接"""

    def __init__(self, self_id: str, websocket: WebSocket) -> None:
        super().__init__(self_id)
        self.websocket = websocket

    async def open(self) -> None:
        await self.websocket.accept()

    async def receive(self) -> dict:
        payload = await self.websocket.receive_json()
        if not isinstance(payload, dict):
            raise TypeError("协议消息必须是 JSON 对象")
        return payload

    async def _send(self, payload: dict) -> None:
        await self.websocket.send_json(payload)

    async def close(self, code: int = 1001) -> None:
        self.ready = False
        await self.websocket.close(code=code)


# TODO: Satori 连接复用上述契约，具体鉴权、心跳和多 Login 行为由其实现负责。
