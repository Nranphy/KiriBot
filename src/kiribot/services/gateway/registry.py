"""Gateway 外部会话和内部订阅者注册表"""

import asyncio
from dataclasses import dataclass, field

from kiribot.services.gateway.models import (
    ConnectionKey,
    ConnectionState,
    GatewayProtocol,
    SubscriberKey,
)
from kiribot.services.gateway.transport import Connection


@dataclass
class ExternalSession:
    """一个按配置名称登记的外部协议会话"""

    name: str
    protocol: GatewayProtocol
    connection: Connection


@dataclass
class Subscriber:
    """带有限发送队列的内部客户端"""

    connection_name: str
    client_id: str
    protocol: GatewayProtocol
    connection: Connection
    queue_size: int = 100
    queue: asyncio.Queue[dict] = field(init=False)
    writer_task: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.queue = asyncio.Queue(self.queue_size)

    def start(self) -> None:
        if self.writer_task is None:
            self.writer_task = asyncio.create_task(self._write_messages())

    def publish(self, payload: dict) -> bool:
        """非阻塞入队；队列满表示客户端已经落后"""
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            return False
        return True

    async def _write_messages(self) -> None:
        try:
            while True:
                await self.connection.send(await self.queue.get())
        except asyncio.CancelledError:
            raise
        except OSError, RuntimeError:
            self.connection.ready = False
            try:
                await self.connection.close()
            except RuntimeError:
                pass

    async def close(self, code: int = 1001) -> None:
        if self.writer_task is not None:
            self.writer_task.cancel()
            await asyncio.gather(self.writer_task, return_exceptions=True)
            self.writer_task = None
        try:
            await self.connection.close(code)
        except RuntimeError:
            pass


class ConnectionRegistry:
    """保证连接名称、客户端名称与协议类型的一致性"""

    def __init__(self) -> None:
        self.external: dict[ConnectionKey, ExternalSession] = {}
        self.subscribers: dict[SubscriberKey, Subscriber] = {}
        self.states: dict[ConnectionKey, ConnectionState] = {}

    def register_external(self, session: ExternalSession) -> None:
        key = ConnectionKey(session.name, session.protocol)
        if any(existing.name == session.name for existing in self.external):
            raise ValueError('外部连接名称已被占用')
        self.external[key] = session
        self.states[key] = ConnectionState.CONNECTING

    def remove_external(self, name: str, connection: Connection) -> None:
        key = next((key for key in self.external if key.name == name), None)
        current = self.external.get(key) if key is not None else None
        if key is not None and current is not None and current.connection is connection:
            self.external.pop(key)
            self.states[key] = ConnectionState.STOPPED

    def get_external(self, name: str, protocol: GatewayProtocol) -> ExternalSession | None:
        key = ConnectionKey(name, protocol)
        session = self.external.get(key)
        if session is None or self.states.get(key) != ConnectionState.READY:
            return None
        return session

    def mark_external_connecting(self, name: str, protocol: GatewayProtocol) -> None:
        self.states[ConnectionKey(name, protocol)] = ConnectionState.CONNECTING

    def mark_external_waiting(self, name: str, protocol: GatewayProtocol) -> None:
        self.states[ConnectionKey(name, protocol)] = ConnectionState.WAITING

    def mark_external_ready(self, name: str, protocol: GatewayProtocol) -> None:
        self.states[ConnectionKey(name, protocol)] = ConnectionState.READY

    def mark_external_reconnecting(self, name: str, protocol: GatewayProtocol) -> None:
        self.states[ConnectionKey(name, protocol)] = ConnectionState.RECONNECTING

    def register_subscriber(self, subscriber: Subscriber) -> None:
        external = self.get_external(subscriber.connection_name, subscriber.protocol)
        if external is None or not external.connection.ready:
            raise ConnectionError('外部连接未就绪')
        key = SubscriberKey(subscriber.connection_name, subscriber.client_id)
        if key in self.subscribers:
            raise ValueError('内部客户端名称已被占用')
        self.subscribers[key] = subscriber
        subscriber.start()

    def remove_subscriber(self, subscriber: Subscriber) -> None:
        key = SubscriberKey(subscriber.connection_name, subscriber.client_id)
        if self.subscribers.get(key) is subscriber:
            self.subscribers.pop(key)

    def get_subscribers(self, connection_name: str, protocol: GatewayProtocol) -> list[Subscriber]:
        return [
            subscriber
            for key, subscriber in self.subscribers.items()
            if key.connection_name == connection_name
            and subscriber.protocol == protocol
            and subscriber.connection.ready
        ]

    async def disconnect_subscribers(self, connection_name: str) -> None:
        clients = [subscriber for key, subscriber in self.subscribers.items() if key.connection_name == connection_name]
        for subscriber in clients:
            self.remove_subscriber(subscriber)
        await asyncio.gather(*(subscriber.close() for subscriber in clients), return_exceptions=True)

    async def close(self) -> None:
        names = {key.connection_name for key in self.subscribers}
        await asyncio.gather(
            *(self.disconnect_subscribers(name) for name in names),
            return_exceptions=True,
        )
        sessions = list(self.external.values())
        self.external.clear()
        for key in self.states:
            self.states[key] = ConnectionState.STOPPED
        await asyncio.gather(
            *(session.connection.close() for session in sessions),
            return_exceptions=True,
        )
