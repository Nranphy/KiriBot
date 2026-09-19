"""OneBot 11 事件广播和 Action 请求关联"""

import asyncio
from uuid import uuid4

from fastapi import WebSocketDisconnect
from websockets.exceptions import WebSocketException

from kiribot.models.users import ChatPlatform
from kiribot.services.gateway.models import GatewayProtocol
from kiribot.services.gateway.observation import UserObservationSink
from kiribot.services.gateway.onebot11.extractor import extract_user_observation
from kiribot.services.gateway.registry import ConnectionRegistry
from kiribot.services.gateway.transport import Connection


class OneBot11Router:
    def __init__(
        self,
        registry: ConnectionRegistry,
        timeout: float,
        observation_sink: UserObservationSink | None,
        platforms: dict[str, ChatPlatform],
    ) -> None:
        self.registry = registry
        self.timeout = timeout
        self.observation_sink = observation_sink
        self.platforms = platforms
        self.tasks: set[asyncio.Task[None]] = set()
        self.pending: dict[str, tuple[str, asyncio.Future[dict]]] = {}

    async def route(self, connection_name: str, self_id: str, payload: dict) -> None:
        if 'post_type' in payload:
            if str(payload.get('self_id')) != self_id:
                raise ValueError('事件 self_id 与连接账号不一致')
            if payload['post_type'] == 'meta_event':
                return
            observation = extract_user_observation(
                payload,
                self.platforms[connection_name],
            )
            if observation is not None and self.observation_sink is not None:
                self.observation_sink.submit(observation)
            for subscriber in self.registry.get_subscribers(connection_name, GatewayProtocol.ONEBOT_V11):
                if not subscriber.publish(payload):
                    await subscriber.close(code=1013)
                    self.registry.remove_subscriber(subscriber)
            return
        echo = payload.get('echo')
        pending = self.pending.get(echo) if isinstance(echo, str) else None
        if pending is not None and pending[0] == connection_name and not pending[1].done():
            pending[1].set_result(payload)

    async def action(self, connection_name: str, client: Connection, payload: dict) -> None:
        echo = uuid4().hex
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self.pending[echo] = (connection_name, future)
        try:
            async with asyncio.timeout(self.timeout):
                session = self.registry.get_external(connection_name, GatewayProtocol.ONEBOT_V11)
                if session is None:
                    raise ConnectionError('机器人未连接')
                await session.connection.send({**payload, 'echo': echo})
                response = await future
        except (
            TimeoutError,
            ConnectionError,
            OSError,
            RuntimeError,
            WebSocketDisconnect,
            WebSocketException,
        ):
            response = {'status': 'failed', 'retcode': 1503, 'data': None}
        finally:
            self.pending.pop(echo, None)
        response = dict(response)
        if 'echo' in payload:
            response['echo'] = payload['echo']
        else:
            response.pop('echo', None)
        try:
            await client.send(response)
        except OSError, RuntimeError, WebSocketDisconnect, WebSocketException:
            pass

    def start_action(self, connection_name: str, client: Connection, payload: dict) -> None:
        if not isinstance(payload.get('action'), str):
            raise TypeError('缺少 OneBot Action')
        task = asyncio.create_task(self.action(connection_name, client, payload))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def external_disconnected(self, connection_name: str) -> None:
        for pending_name, future in self.pending.values():
            if pending_name == connection_name and not future.done():
                future.set_exception(ConnectionError('机器人连接已断开'))

    async def close(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.pending.clear()
