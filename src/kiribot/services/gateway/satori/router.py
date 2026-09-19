"""Satori EVENT、META 与 PONG 路由"""

import asyncio

from kiribot.services.gateway.models import GatewayProtocol
from kiribot.services.gateway.registry import ConnectionRegistry
from kiribot.services.gateway.satori.session import SatoriExternalSession


class SatoriRouter:
    def __init__(self, registry: ConnectionRegistry) -> None:
        self.registry = registry
        self.pongs: dict[str, asyncio.Event] = {}

    async def route(self, connection_name: str, payload: dict) -> None:
        for subscriber in self.registry.get_subscribers(connection_name, GatewayProtocol.SATORI):
            if not subscriber.publish(payload):
                await subscriber.close(code=1013)
                self.registry.remove_subscriber(subscriber)

    async def handle_external(self, connection: SatoriExternalSession, payload: dict) -> None:
        opcode = payload.get('op')
        if opcode == 0:
            body = payload.get('body')
            if not isinstance(body, dict):
                raise TypeError('Satori EVENT body 必须是 JSON 对象')
            sequence = body.get('sn', body.get('id'))
            if isinstance(sequence, int):
                connection.sequence = sequence
            await self.route(connection.connection_name, payload)
        elif opcode == 2:
            self.pongs.setdefault(connection.connection_name, asyncio.Event()).set()
        elif opcode == 5:
            await self.route(connection.connection_name, payload)
        else:
            raise ValueError('外部 Satori 服务发送了非法信令')
