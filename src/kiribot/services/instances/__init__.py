"""Worker 实例管理服务"""

from functools import lru_cache

from kiribot.infra.config import get_settings
from kiribot.services.gateway import get_gateway_service
from kiribot.services.instances.service import (
    InstanceAlreadyRunningError,
    InstanceNotFoundError,
    InstanceNotRunningError,
    InstanceService,
    InvalidInstanceConfigError,
)


@lru_cache
def get_instance_service() -> InstanceService:
    """按 Manager 与 Gateway 配置创建进程内共享的实例服务"""
    settings = get_settings()
    gateway = get_gateway_service()
    return InstanceService.from_config_file(
        settings.instances_config_path,
        gateway.config,
        gateway.internal_token,
        settings.host,
        settings.port,
    )


__all__ = [
    'InstanceAlreadyRunningError',
    'InstanceNotFoundError',
    'InstanceNotRunningError',
    'InstanceService',
    'InvalidInstanceConfigError',
    'get_instance_service',
]
