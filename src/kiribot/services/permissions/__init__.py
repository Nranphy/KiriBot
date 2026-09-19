"""用户权限服务"""

from functools import lru_cache

from kiribot.clients.database import get_database_client
from kiribot.infra.config import get_settings
from kiribot.services.permissions.service import (
    GroupNotFoundError,
    InvalidPermissionScopeError,
    PermissionDeniedError,
    PermissionService,
    UserNotFoundError,
)


@lru_cache
def get_permission_service() -> PermissionService:
    settings = get_settings()
    return PermissionService.from_config_file(
        get_database_client(),
        settings.permissions_config_path,
    )


__all__ = [
    'GroupNotFoundError',
    'InvalidPermissionScopeError',
    'PermissionDeniedError',
    'PermissionService',
    'UserNotFoundError',
    'get_permission_service',
]
