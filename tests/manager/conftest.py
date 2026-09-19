"""Manager 测试的进程级框架状态隔离"""

from collections.abc import Generator

import nonebot
import pytest
from nonebot.internal.driver import Driver

from kiribot.infra.config import get_settings
from kiribot.services.gateway import get_gateway_service
from kiribot.services.instances import get_instance_service


@pytest.fixture(autouse=True)
def reset_nonebot_driver(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """避免 NoneBot Driver 与 Adapter 在应用工厂测试之间复用旧配置"""
    get_instance_service.cache_clear()
    get_gateway_service.cache_clear()
    get_settings.cache_clear()
    monkeypatch.setattr(nonebot, '_driver', None)
    Driver._adapters.clear()
    yield
    get_instance_service.cache_clear()
    get_gateway_service.cache_clear()
    get_settings.cache_clear()
