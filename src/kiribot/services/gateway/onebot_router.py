"""OneBot 11 事件广播和 Action 请求关联"""

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import WebSocketDisconnect
from websockets.exceptions import WebSocketException

from kiribot.services.gateway.connection import Connection

if TYPE_CHECKING:
    from kiribot.services.gateway.gateway import Gateway


class OneBot11Router:
    """协议专属的事件与请求路由，不负责建立或重连 WS"""

    def __init__(self, gateway: Gateway, request_timeout: float) -> None:
        self.gateway = gateway
        self.request_timeout = request_timeout
        self.tasks: set[asyncio.Task[None]] = set()
        self.pending: dict[str, tuple[str, asyncio.Future[dict]]] = {}

    async def route(self, self_id: str, payload: dict) -> None:
        """处理外部事件或 Action 响应，保留协议数据"""
        if 'post_type' in payload:
            if str(payload.get('self_id')) != self_id:
                raise ValueError('事件 self_id 与连接账号不一致')
            if payload['post_type'] == 'meta_event':
                # 内部生命周期独立维护，不透传外部生命周期或心跳。
                return
            for client in self.event_targets(self_id):
                try:
                    await client.send(payload)
                except OSError, RuntimeError, WebSocketDisconnect, WebSocketException:
                    continue
        else:
            echo = payload.get('echo')
            pending = self.pending.get(echo) if isinstance(echo, str) else None
            if pending is not None and pending[0] == self_id and not pending[1].done():
                pending[1].set_result(payload)

    def event_targets(self, self_id: str) -> list[Connection]:
        """默认向该账号的 Manager 和全部就绪 Worker 分发事件

        OneBot 11 WS 按账号建立，一个 Worker 可为多个账号分别连接。
        后续在此接入外部服务到 Worker 实例的路由管理规则。
        """
        return [client for client in self.gateway.clients.get(self_id, {}).values() if client.ready]

    async def action(self, self_id: str, client: Connection, payload: dict) -> None:
        """转发 Action，映射 echo 并限制响应等待时间"""
        echo = uuid4().hex
        response: dict
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self.pending[echo] = (self_id, future)
        try:
            async with asyncio.timeout(self.request_timeout):
                account = self.gateway.accounts.get(self_id)
                if account is None:
                    raise ConnectionError('机器人未连接')
                await account.send({**payload, 'echo': echo})
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

    def start_action(self, self_id: str, client: Connection, payload: dict) -> None:
        """独立等待响应，避免阻塞客户端接收后续 Action"""
        if not isinstance(payload.get('action'), str):
            raise TypeError('缺少 OneBot Action')
        task = asyncio.create_task(self.action(self_id, client, payload))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self) -> None:
        """取消待响应的请求并清理关联表"""
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.pending.clear()
