"""OneBot 11 连接握手与协议行为"""

import time
from typing import TYPE_CHECKING

from kiribot.models.gateway import ExternalConnectionConfig
from kiribot.services.gateway.connection import ForwardConnection, ReverseConnection

if TYPE_CHECKING:
    from kiribot.services.gateway.gateway import Gateway


def validate_self_id(self_id: str) -> None:
    """OneBot 11 账号必须为 ASCII 十进制字符串"""
    if not self_id.isascii() or not self_id.isdecimal():
        raise ValueError('OneBot 11 账号必须为数字')


def lifecycle(self_id: str) -> dict:
    """内部就绪表示 Gateway 协议连接可用，与外部在线状态无关"""
    return {
        'time': int(time.time()),
        'self_id': int(self_id),
        'post_type': 'meta_event',
        'meta_event_type': 'lifecycle',
        'sub_type': 'connect',
    }


class OneBot11ReverseConnection(ReverseConnection):
    """OneBot 11 被动连接，可接收外部事件或内部 Worker Action"""

    def validate(self, config: ExternalConnectionConfig | None = None) -> None:
        """校验账号；外部连接额外检查 Universal 角色、令牌和账号限制"""
        validate_self_id(self.self_id)
        if config is None:
            return
        headers = self.websocket.headers
        if headers.get('x-client-role', '').lower() != 'universal':
            raise ValueError('仅支持 Universal 连接')
        if config.self_id is not None and config.self_id != self.self_id:
            raise ValueError('连接账号与登记账号不一致')
        if config.token and headers.get('authorization') != f'Bearer {config.token}':
            raise ValueError('连接令牌不匹配')

    async def handshake(self) -> None:
        self.ready = True

    async def handle(self, gateway: Gateway, payload: dict) -> None:
        await gateway.onebot.route(self.self_id, payload)


class OneBot11WorkerConnection(OneBot11ReverseConnection):
    """Worker 内部连接，独立发送就绪并接收 Action"""

    async def handshake(self) -> None:
        await self.send(lifecycle(self.self_id))
        self.ready = True

    async def handle(self, gateway: Gateway, payload: dict) -> None:
        gateway.onebot.start_action(self.self_id, self, payload)


class OneBot11ForwardConnection(ForwardConnection):
    """
    主动连接 Manager 的 OneBot 11 反向端点

    正向表示 Gateway 主动建立传输，不表示已实现外部 OneBot 正向接入。
    """

    def headers(self) -> dict[str, str]:
        return {'X-Self-ID': self.self_id, 'X-Client-Role': 'Universal'}

    async def handshake(self) -> None:
        validate_self_id(self.self_id)
        await self.send(lifecycle(self.self_id))
        self.ready = True

    async def handle(self, gateway: Gateway, payload: dict) -> None:
        gateway.onebot.start_action(self.self_id, self, payload)


# TODO: 外部 OneBot 11 正向连接需实现上游握手与事件接收，不能复用 Manager 握手。
