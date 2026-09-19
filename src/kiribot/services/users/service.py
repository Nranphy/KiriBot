"""用户和群聊自动记录业务服务"""

from kiribot.clients.database import DatabaseClient, UserRepository
from kiribot.models.users import UserObservation


class UserService:
    """在单个事务中维护用户、平台身份和群聊信息"""

    def __init__(self, database: DatabaseClient) -> None:
        self.database = database

    async def record(self, observation: UserObservation) -> None:
        async with self.database.transaction() as session:
            await UserRepository(session).record(observation)
