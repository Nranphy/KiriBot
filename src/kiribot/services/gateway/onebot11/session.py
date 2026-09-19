"""OneBot 11 外部与内部 WebSocket 会话"""

import asyncio
import time

from fastapi import WebSocket

from kiribot.models.gateway import OneBot11ForwardConfig, OneBot11ReverseConfig
from kiribot.services.gateway.transport import ForwardConnection, ReverseConnection


def validate_self_id(self_id: str) -> None:
    if not self_id.isascii() or not self_id.isdecimal():
        raise ValueError('OneBot 11 账号必须为数字')


def lifecycle(self_id: str) -> dict:
    return {
        'time': int(time.time()),
        'self_id': int(self_id),
        'post_type': 'meta_event',
        'meta_event_type': 'lifecycle',
        'sub_type': 'connect',
    }


class OneBot11ForwardSession(ForwardConnection):
    """Gateway 主动连接的 OneBot 11 Universal 会话"""

    def __init__(self, connection_name: str, config: OneBot11ForwardConfig) -> None:
        super().__init__(connection_name, str(config.url))
        self.token = config.token
        self.expected_self_id = config.self_id
        self.self_id = ''
        self.initial_payloads: list[dict] = []

    def headers(self) -> dict[str, str]:
        if self.token is None:
            return {}
        return {'Authorization': f'Bearer {self.token}'}

    async def handshake(self) -> None:
        """等待标准 lifecycle connect，以确认连接对应的机器人账号"""
        async with asyncio.timeout(10):
            while True:
                payload = await self.receive()
                if (
                    payload.get('post_type') == 'meta_event'
                    and payload.get('meta_event_type') == 'lifecycle'
                    and payload.get('sub_type') == 'connect'
                ):
                    self_id = str(payload.get('self_id', ''))
                    validate_self_id(self_id)
                    if self.expected_self_id is not None and self.expected_self_id != self_id:
                        raise ValueError('连接账号与登记账号不一致')
                    self.self_id = self_id
                    self.ready = True
                    return
                if len(self.initial_payloads) >= 100:
                    raise ValueError('OneBot 11 握手前消息过多')
                self.initial_payloads.append(payload)


class OneBot11ReverseSession(ReverseConnection):
    """外部 OneBot 11 Universal 反向连接"""

    def __init__(self, connection_name: str, self_id: str, websocket: WebSocket) -> None:
        super().__init__(connection_name, websocket)
        self.self_id = self_id

    def validate(self, config: OneBot11ReverseConfig) -> None:
        validate_self_id(self.self_id)
        headers = self.websocket.headers
        if headers.get('x-client-role', '').lower() != 'universal':
            raise ValueError('仅支持 Universal 连接')
        if config.self_id is not None and config.self_id != self.self_id:
            raise ValueError('连接账号与登记账号不一致')
        if config.token and headers.get('authorization') != f'Bearer {config.token}':
            raise ValueError('连接令牌不匹配')

    async def handshake(self) -> None:
        self.ready = True


class OneBot11InternalSession(OneBot11ReverseSession):
    """Manager 或 Worker 的内部 OneBot 会话"""

    async def handshake(self) -> None:
        await self.send(lifecycle(self.self_id))
        self.ready = True
