"""Gateway 领域服务"""

from functools import lru_cache

from kiribot.infra.config import get_settings
from kiribot.services.gateway.service import GatewayService
from kiribot.services.users import get_user_recorder


@lru_cache
def get_gateway_service() -> GatewayService:
    """按 Manager 配置创建进程内共享的 Gateway 服务"""
    settings = get_settings()
    return GatewayService.from_config_file(
        settings.gateway_config_path,
        get_user_recorder(),
    )


__all__ = ['GatewayService', 'get_gateway_service']
