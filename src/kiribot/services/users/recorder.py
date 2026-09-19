"""不阻塞 Gateway 转发的用户观察队列"""

import asyncio

from loguru import logger

from kiribot.models.users import UserObservation
from kiribot.services.users.service import UserService


class UserRecorder:
    """使用单个后台任务串行写入 SQLite"""

    def __init__(self, service: UserService, queue_size: int = 1024) -> None:
        self.service = service
        self.queue: asyncio.Queue[UserObservation] = asyncio.Queue(queue_size)
        self.task: asyncio.Task[None] | None = None
        self.accepting = False

    def submit(self, observation: UserObservation) -> bool:
        if not self.accepting:
            return False
        try:
            self.queue.put_nowait(observation)
        except asyncio.QueueFull:
            logger.warning('用户观察队列已满，丢弃本次自动记录')
            return False
        return True

    async def start(self) -> None:
        if self.task is not None:
            return
        self.accepting = True
        self.task = asyncio.create_task(self._consume())

    async def close(self) -> None:
        self.accepting = False
        if self.task is None:
            return
        await self.queue.join()
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.task = None

    async def _consume(self) -> None:
        while True:
            observation = await self.queue.get()
            try:
                await self.service.record(observation)
            except Exception:  # noqa: BLE001 - 后台记录失败不得中止事件消费
                logger.exception('自动记录用户信息失败')
            finally:
                self.queue.task_done()
