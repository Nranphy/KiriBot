"""OneBot 11 Gateway 协议服务"""

import asyncio
import random

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from websockets.exceptions import WebSocketException

from kiribot.models.gateway import (
    GatewayConfig,
    OneBot11ForwardConfig,
    OneBot11ReverseConfig,
)
from kiribot.services.gateway.models import GatewayProtocol
from kiribot.services.gateway.observation import UserObservationSink
from kiribot.services.gateway.onebot11.router import OneBot11Router
from kiribot.services.gateway.onebot11.session import (
    OneBot11ForwardSession,
    OneBot11InternalSession,
    OneBot11ReverseSession,
)
from kiribot.services.gateway.registry import (
    ConnectionRegistry,
    ExternalSession,
    Subscriber,
)


class OneBot11Gateway:
    """管理 OneBot 外部接入、内部会话和 Action 路由"""

    def __init__(
        self,
        registry: ConnectionRegistry,
        config: GatewayConfig,
        internal_token: str,
        timeout: float,
        observation_sink: UserObservationSink | None,
    ) -> None:
        self.registry = registry
        self.config = config
        self.internal_token = internal_token
        platforms = {name: config.platform for name, config in config.connections.items()}
        self.router = OneBot11Router(registry, timeout, observation_sink, platforms)
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.started = False

    async def start(self) -> None:
        """启动正向连接任务，并将反向配置置为等待接入"""
        if self.started:
            return
        self.started = True
        for name, config in self.config.connections.items():
            if isinstance(config, OneBot11ForwardConfig):
                self.tasks[name] = asyncio.create_task(self._run_forward(name, config))
            elif isinstance(config, OneBot11ReverseConfig):
                self.registry.mark_external_waiting(name, GatewayProtocol.ONEBOT_V11)

    async def _run_forward(self, name: str, config: OneBot11ForwardConfig) -> None:
        delay = 1.0
        while True:
            connection = OneBot11ForwardSession(name, config)
            stopping = False
            try:
                self.registry.mark_external_connecting(name, GatewayProtocol.ONEBOT_V11)
                await connection.open()
                await connection.handshake()
                self.registry.register_external(ExternalSession(name, GatewayProtocol.ONEBOT_V11, connection))
                self.registry.mark_external_ready(name, GatewayProtocol.ONEBOT_V11)
                delay = 1.0
                for payload in connection.initial_payloads:
                    await self.router.route(name, connection.self_id, payload)
                connection.initial_payloads.clear()
                while True:
                    await self.router.route(name, connection.self_id, await connection.receive())
            except asyncio.CancelledError:
                stopping = True
                raise
            except (
                TimeoutError,
                ConnectionError,
                OSError,
                ValueError,
                TypeError,
                WebSocketException,
            ) as error:
                logger.warning(
                    '外部 OneBot 11 正向连接 {} 断开：{}',
                    name,
                    type(error).__name__,
                )
            finally:
                self.registry.remove_external(name, connection)
                self.router.external_disconnected(name)
                await self.registry.disconnect_subscribers(name)
                await connection.close()
                if not stopping:
                    self.registry.mark_external_reconnecting(name, GatewayProtocol.ONEBOT_V11)
            await asyncio.sleep(delay + random.uniform(0, delay * 0.2))
            delay = min(delay * 2, 30)

    async def serve_external(self, websocket: WebSocket, name: str) -> None:
        config = self.config.connections.get(name)
        if not isinstance(config, OneBot11ReverseConfig):
            await websocket.close(code=1008)
            return
        connection = OneBot11ReverseSession(name, websocket.headers.get('x-self-id', ''), websocket)
        try:
            connection.validate(config)
            self.registry.register_external(ExternalSession(name, GatewayProtocol.ONEBOT_V11, connection))
        except ValueError:
            await connection.close(code=1008)
            return
        try:
            await connection.open()
            await connection.handshake()
            self.registry.mark_external_ready(name, GatewayProtocol.ONEBOT_V11)
            while True:
                await self.router.route(name, connection.self_id, await connection.receive())
        except WebSocketDisconnect:
            pass
        except ValueError, TypeError:
            await connection.close(code=1008)
        finally:
            self.registry.remove_external(name, connection)
            self.router.external_disconnected(name)
            await self.registry.disconnect_subscribers(name)
            if self.started:
                self.registry.mark_external_waiting(name, GatewayProtocol.ONEBOT_V11)

    async def serve_internal(self, websocket: WebSocket, client_id: str, connection_name: str) -> None:
        if not self._authorized(dict(websocket.headers)):
            await websocket.close(code=1008)
            return
        external = self.registry.get_external(connection_name, GatewayProtocol.ONEBOT_V11)
        if external is None:
            await websocket.close(code=1008)
            return
        self_id = getattr(external.connection, 'self_id', '')
        if not self_id:
            await websocket.close(code=1011)
            return
        connection = OneBot11InternalSession(connection_name, self_id, websocket)
        subscriber = Subscriber(connection_name, client_id, GatewayProtocol.ONEBOT_V11, connection)
        try:
            await connection.open()
            await connection.handshake()
            self.registry.register_subscriber(subscriber)
            while True:
                self.router.start_action(connection_name, connection, await connection.receive())
        except WebSocketDisconnect:
            pass
        except ConnectionError, ValueError, TypeError:
            await subscriber.close(code=1008)
        finally:
            self.registry.remove_subscriber(subscriber)
            await subscriber.close()

    def _authorized(self, headers: dict[str, str]) -> bool:
        return (
            next(
                (value for key, value in headers.items() if key.lower() == 'authorization'),
                None,
            )
            == f'Bearer {self.internal_token}'
        )

    async def close(self) -> None:
        self.started = False
        tasks = list(self.tasks.values())
        self.tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.router.close()
