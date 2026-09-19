"""Gateway 总生命周期与协议服务协调器"""

import secrets
from pathlib import Path

from fastapi import WebSocket

from kiribot.models.gateway import GatewayConfig
from kiribot.services.gateway.models import ConnectionState, ProxyResponse
from kiribot.services.gateway.observation import UserObservationSink
from kiribot.services.gateway.onebot11 import OneBot11Gateway
from kiribot.services.gateway.registry import ConnectionRegistry
from kiribot.services.gateway.satori import SatoriGateway


class GatewayService:
    """装配共享注册表并协调 OneBot、Satori 协议服务"""

    def __init__(
        self,
        config: GatewayConfig | None = None,
        request_timeout: float = 30,
        observation_sink: UserObservationSink | None = None,
    ) -> None:
        self.config = config if config is not None else GatewayConfig()
        self.internal_token = secrets.token_urlsafe(32)
        self.registry = ConnectionRegistry()
        self.onebot11 = OneBot11Gateway(
            self.registry,
            self.config,
            self.internal_token,
            request_timeout,
            observation_sink,
        )
        self.satori = SatoriGateway(
            self.registry,
            self.config,
            self.internal_token,
            request_timeout,
            observation_sink,
        )

    @classmethod
    def from_config_file(
        cls,
        path: Path,
        observation_sink: UserObservationSink | None = None,
    ) -> GatewayService:
        try:
            content = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            config = GatewayConfig()
        else:
            config = GatewayConfig.model_validate_json(content)
        return cls(config, observation_sink=observation_sink)

    @property
    def connection_states(self) -> dict[str, ConnectionState]:
        """返回适合管理面读取的连接状态快照"""
        return {key.name: state for key, state in self.registry.states.items()}

    async def start(self) -> None:
        await self.onebot11.start()
        await self.satori.start()

    async def serve_onebot_external(self, websocket: WebSocket, connection_name: str) -> None:
        await self.onebot11.serve_external(websocket, connection_name)

    async def serve_onebot_internal(self, websocket: WebSocket, client_id: str, connection_name: str) -> None:
        await self.onebot11.serve_internal(websocket, client_id, connection_name)

    async def serve_satori_internal(self, websocket: WebSocket, client_id: str, connection_name: str) -> None:
        await self.satori.serve_internal(websocket, client_id, connection_name)

    async def proxy_satori_api(
        self,
        connection_name: str,
        api_path: str,
        method: str,
        headers: dict[str, str],
        content: bytes,
        query: str = '',
    ) -> ProxyResponse:
        return await self.satori.proxy_api(connection_name, api_path, method, headers, content, query)

    async def close(self) -> None:
        await self.onebot11.close()
        await self.satori.close()
        await self.registry.close()
