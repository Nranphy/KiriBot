"""用户和群聊记录服务"""

from functools import lru_cache

from kiribot.clients.database import get_database_client
from kiribot.services.users.recorder import UserRecorder
from kiribot.services.users.service import UserService


@lru_cache
def get_user_service() -> UserService:
    return UserService(get_database_client())


@lru_cache
def get_user_recorder() -> UserRecorder:
    return UserRecorder(get_user_service())


__all__ = ['UserRecorder', 'UserService', 'get_user_recorder', 'get_user_service']
