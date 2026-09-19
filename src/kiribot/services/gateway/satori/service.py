"""Satori Gateway 协议服务"""

import asyncio
import random
from urllib.parse import urljoin, urlparse, urlunparse

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from websockets.exceptions import WebSocketException

from kiribot.models.gateway import GatewayConfig, SatoriForwardConfig
from kiribot.services.gateway.models import GatewayProtocol, ProxyResponse
from kiribot.services.gateway.registry import (
    ConnectionRegistry,
    ExternalSession,
    Subscriber,
)
from kiribot.services.gateway.satori.api_client import SatoriApiClient
from kiribot.services.gateway.satori.router import SatoriRouter
from kiribot.services.gateway.satori.session import (
    SatoriExternalSession,
    SatoriInternalSession,
)


class SatoriGateway:
    """管理 Satori 外部连接、内部事件服务和 HTTP API 代理"""

    def __init__(
        self,
        registry: ConnectionRegistry,
        config: GatewayConfig,
        internal_token: str,
        timeout: float,
    ) -> None:
        self.registry = registry
        self.config = config
        self.internal_token = internal_token
        self.router = SatoriRouter(registry)
        self.api = SatoriApiClient(timeout)
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.started = False

    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        for name, config in self.config.connections.items():
            if isinstance(config, SatoriForwardConfig):
                connection = SatoriExternalSession(name, self.events_url(str(config.url)), config.token)
                self.tasks[name] = asyncio.create_task(self._run_external(connection))

    @staticmethod
    def events_url(url: str) -> str:
        parsed = urlparse(url)
        scheme = {'http': 'ws', 'https': 'wss', 'ws': 'ws', 'wss': 'wss'}.get(parsed.scheme)
        if scheme is None or not parsed.netloc:
            raise ValueError('Satori url 必须是有效的 HTTP(S) 或 WS(S) 地址')
        return urlunparse(
            parsed._replace(
                scheme=scheme,
                path=urljoin(parsed.path.rstrip('/') + '/', 'v1/events'),
                query='',
            )
        )

    async def _run_external(self, connection: SatoriExternalSession) -> None:
        delay = 1.0
        while True:
            heartbeat: asyncio.Task[None] | None = None
            stopping = False
            try:
                self.registry.mark_external_connecting(connection.connection_name, GatewayProtocol.SATORI)
                await connection.open()
                await connection.handshake()
                self.registry.register_external(
                    ExternalSession(connection.connection_name, GatewayProtocol.SATORI, connection)
                )
                self.registry.mark_external_ready(connection.connection_name, GatewayProtocol.SATORI)
                heartbeat = asyncio.create_task(self._heartbeat(connection))
                delay = 1.0
                while True:
                    await self.router.handle_external(connection, await connection.receive())
            except asyncio.CancelledError:
                stopping = True
                raise
            except (OSError, WebSocketException, ValueError, TypeError) as error:
                logger.warning(
                    '外部 Satori 连接 {} 断开：{}',
                    connection.connection_name,
                    type(error).__name__,
                )
            finally:
                if heartbeat is not None:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
                self.registry.remove_external(connection.connection_name, connection)
                if not stopping:
                    self.registry.mark_external_reconnecting(connection.connection_name, GatewayProtocol.SATORI)
                await self.registry.disconnect_subscribers(connection.connection_name)
                await connection.close()
            await asyncio.sleep(delay + random.uniform(0, delay * 0.2))
            delay = min(delay * 2, 30)

    async def _heartbeat(self, connection: SatoriExternalSession) -> None:
        pong = self.router.pongs.setdefault(connection.connection_name, asyncio.Event())
        while True:
            pong.clear()
            await connection.send({'op': 1, 'body': {}})
            try:
                async with asyncio.timeout(10):
                    await pong.wait()
            except TimeoutError:
                await connection.close(code=1011)
                raise

    async def serve_internal(self, websocket: WebSocket, client_id: str, connection_name: str) -> None:
        external = self.registry.get_external(connection_name, GatewayProtocol.SATORI)
        if external is None or not isinstance(external.connection, SatoriExternalSession):
            await websocket.close(code=1008)
            return
        if external.connection.ready_payload is None:
            await websocket.close(code=1011)
            return
        connection = SatoriInternalSession(
            connection_name,
            websocket,
            external.connection.ready_payload,
            self.internal_token,
        )
        subscriber = Subscriber(connection_name, client_id, GatewayProtocol.SATORI, connection)
        try:
            await connection.open()
            await connection.handshake()
            self.registry.register_subscriber(subscriber)
            while True:
                payload = await connection.receive()
                if payload.get('op') != 1:
                    raise ValueError('内部 Satori 客户端仅可发送 PING')
                await connection.send({'op': 2, 'body': {}})
        except WebSocketDisconnect:
            pass
        except ConnectionError, ValueError, TypeError:
            await subscriber.close(code=1008)
        finally:
            self.registry.remove_subscriber(subscriber)
            await subscriber.close()

    async def proxy_api(
        self,
        connection_name: str,
        api_path: str,
        method: str,
        headers: dict[str, str],
        content: bytes,
        query: str = '',
    ) -> ProxyResponse:
        if not self._authorized(headers):
            return ProxyResponse(401, {})
        config = self.config.connections.get(connection_name)
        external = self.registry.get_external(connection_name, GatewayProtocol.SATORI)
        if not isinstance(config, SatoriForwardConfig) or external is None:
            return ProxyResponse(503, {})
        return await self.api.request(str(config.url), config.token, api_path, method, headers, content, query)

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
        await self.api.close()
