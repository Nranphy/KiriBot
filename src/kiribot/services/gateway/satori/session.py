"""Satori 外部与内部 WebSocket 会话"""

from fastapi import WebSocket

from kiribot.services.gateway.transport import ForwardConnection, ReverseConnection


class SatoriExternalSession(ForwardConnection):
    def __init__(self, connection_name: str, url: str, token: str | None) -> None:
        super().__init__(connection_name, url)
        self.token = token
        self.sequence: int | None = None
        self.ready_payload: dict | None = None

    def headers(self) -> dict[str, str]:
        return {}

    async def handshake(self) -> None:
        body: dict[str, str | int] = {}
        if self.token is not None:
            body['token'] = self.token
        if self.sequence is not None:
            body['sn'] = self.sequence
        await self.send({'op': 3, 'body': body})
        payload = await self.receive()
        if payload.get('op') != 4 or not isinstance(payload.get('body'), dict):
            raise ValueError('Satori 服务未返回 READY')
        self.ready_payload = payload
        self.ready = True


class SatoriInternalSession(ReverseConnection):
    def __init__(
        self,
        connection_name: str,
        websocket: WebSocket,
        ready_payload: dict,
        expected_token: str | None,
    ) -> None:
        super().__init__(connection_name, websocket)
        self.ready_payload = ready_payload
        self.expected_token = expected_token

    async def handshake(self) -> None:
        payload = await self.receive()
        if payload.get('op') != 3 or not isinstance(payload.get('body'), dict):
            raise ValueError('内部 Satori 客户端必须先发送 IDENTIFY')
        if self.expected_token is not None and payload['body'].get('token') != self.expected_token:
            raise ValueError('内部 Satori 客户端令牌不匹配')
        await self.send(self.ready_payload)
        self.ready = True
