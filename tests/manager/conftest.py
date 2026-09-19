"""Manager 测试的进程级框架状态隔离"""

from collections.abc import Generator
from pathlib import Path

import nonebot
import pytest
from nonebot.internal.driver import Driver

from kiribot.clients.database import get_database_client
from kiribot.infra.config import get_settings
from kiribot.services.gateway import get_gateway_service
from kiribot.services.instances import get_instance_service
from kiribot.services.users import get_user_recorder, get_user_service


@pytest.fixture(autouse=True)
def reset_nonebot_driver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[None]:
    """避免 NoneBot Driver 与 Adapter 在应用工厂测试之间复用旧配置"""
    get_instance_service.cache_clear()
    get_gateway_service.cache_clear()
    get_user_recorder.cache_clear()
    get_user_service.cache_clear()
    get_database_client.cache_clear()
    get_settings.cache_clear()
    monkeypatch.setenv(
        "KIRIBOT_GATEWAY_CONFIG_PATH",
        str(tmp_path / "missing-gateway.json"),
    )
    monkeypatch.setenv(
        "KIRIBOT_INSTANCES_CONFIG_PATH",
        str(tmp_path / "missing-instances.json"),
    )
    monkeypatch.setenv(
        "KIRIBOT_DATABASE_URL",
        f"sqlite+aiosqlite:///{(tmp_path / 'kiribot.db').as_posix()}",
    )
    monkeypatch.setattr(nonebot, "_driver", None)
    Driver._adapters.clear()
    yield
    get_instance_service.cache_clear()
    get_gateway_service.cache_clear()
    get_user_recorder.cache_clear()
    get_user_service.cache_clear()
    get_database_client.cache_clear()
    get_settings.cache_clear()
