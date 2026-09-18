"""Gateway 连接登记、生命周期与重连调度"""

import asyncio
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from websockets.exceptions import WebSocketException

from kiribot.models.gateway import GatewayConfig
from kiribot.services.gateway.connection import Connection, ForwardConnection
from kiribot.services.gateway.onebot_connection import (
    OneBot11ForwardConnection,
    OneBot11ReverseConnection,
    OneBot11WorkerConnection,
)
from kiribot.services.gateway.onebot_router import OneBot11Router


class Gateway:
    """管理连接注册、会话与重连；协议握手和消息行为交给连接实现"""

    def __init__(
        self,
        config: GatewayConfig | None = None,
        request_timeout: float = 30,
        manager_url: str | None = None,
    ) -> None:
        self.config = config if config is not None else GatewayConfig()
        self.external: dict[str, Connection] = {}
        self.accounts: dict[str, Connection] = {}
        self.clients: dict[str, dict[str, Connection]] = {}
        self.manager_url = manager_url
        self.manager_tasks: dict[str, asyncio.Task[None]] = {}
        self.onebot = OneBot11Router(self, request_timeout)

    @classmethod
    def from_config_file(cls, path: Path, manager_url: str) -> Gateway:
        """读取登记配置，缺失时使用空配置，不创建或覆盖文件"""
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            config = GatewayConfig()
        else:
            config = GatewayConfig.model_validate_json(content)
        return cls(config, manager_url=manager_url)

    async def _receive(self, connection: Connection) -> None:
        """使用统一连接契约进行握手与接收，不解析协议消息"""
        await connection.open()
        await connection.handshake()
        await self._receive_messages(connection)

    async def _receive_messages(self, connection: Connection) -> None:
        """将已就绪连接的消息交给其协议实现"""
        while True:
            await connection.handle(self, await connection.receive())

    def ensure_manager(self, self_id: str) -> None:
        """首次发现账号时启动独立内部连接任务"""
        if self.manager_url is not None and self_id not in self.manager_tasks:
            connection = OneBot11ForwardConnection(self_id, self.manager_url)
            self.manager_tasks[self_id] = asyncio.create_task(
                self._reconnect(connection, "manager")
            )

    async def _reconnect(self, connection: ForwardConnection, client_id: str) -> None:
        """主动连接断开后重试；外部连接断开不影响本任务"""
        while True:
            try:
                await connection.open()
                await connection.handshake()
                self.clients.setdefault(connection.self_id, {})[client_id] = connection
                await self._receive_messages(connection)
            except OSError, WebSocketException, ValueError, TypeError:
                logger.debug(
                    "内部连接 {} / {} 断开，稍后重试", client_id, connection.self_id
                )
            finally:
                clients = self.clients.get(connection.self_id, {})
                if clients.get(client_id) is connection:
                    clients.pop(client_id)
                if not clients:
                    self.clients.pop(connection.self_id, None)
                await connection.close()
            await asyncio.sleep(3)

    async def serve_internal(
        self, websocket: WebSocket, client_id: str, self_id: str
    ) -> None:
        """登记 Worker 连接并调度其会话"""
        connection = OneBot11WorkerConnection(self_id, websocket)
        try:
            connection.validate()
        except ValueError:
            await connection.close(code=1008)
            return
        if client_id == "manager" or client_id in self.clients.get(self_id, {}):
            await connection.close(code=1008)
            return
        clients = self.clients.setdefault(self_id, {})
        clients[client_id] = connection
        try:
            await self._receive(connection)
        except WebSocketDisconnect:
            pass
        except ValueError, TypeError:
            await connection.close(code=1008)
        finally:
            connection.ready = False
            if clients.get(client_id) is connection:
                clients.pop(client_id)
            if not clients:
                self.clients.pop(self_id, None)

    async def serve_external(self, websocket: WebSocket, name: str) -> None:
        """按登记配置选择连接实现，拒绝未实现模式及重复连接"""
        config = self.config.connections.get(name)
        if (
            config is None
            or config.protocol != "onebot_v11"
            or config.mode != "reverse"
        ):
            await websocket.close(code=1008)
            return
        connection = OneBot11ReverseConnection(
            websocket.headers.get("x-self-id", ""), websocket
        )
        try:
            connection.validate(config)
        except ValueError:
            await connection.close(code=1008)
            return
        self_id = connection.self_id
        if name in self.external or self_id in self.accounts:
            await connection.close(code=1008)
            return
        self.external[name] = connection
        self.accounts[self_id] = connection
        try:
            self.ensure_manager(self_id)
            await self._receive(connection)
        except WebSocketDisconnect:
            pass
        except ValueError, TypeError:
            await connection.close(code=1008)
        finally:
            connection.ready = False
            if self.external.get(name) is connection:
                self.external.pop(name)
            if self.accounts.get(self_id) is connection:
                self.accounts.pop(self_id)

    async def close(self) -> None:
        """停止重连、取消协议请求并释放全部连接"""
        tasks = list(self.manager_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.manager_tasks.clear()
        await self.onebot.close()
        connections = set(self.accounts.values()) | {
            connection
            for clients in self.clients.values()
            for connection in clients.values()
        }
        for connection in connections:
            try:
                await connection.close()
            except RuntimeError:
                pass
        self.accounts.clear()
        self.external.clear()
        self.clients.clear()


# TODO: 按配置建立外部正向连接，并为 Satori 选择独立的连接实现。
# TODO: Satori 反向 WS 需明确兼容约定，不能假定为标准模式。
# TODO: 消息缓存与补发暂不实现，内部连接未就绪期间的事件直接丢弃。
# TODO: 增加事件队列背压和配置热加载。
