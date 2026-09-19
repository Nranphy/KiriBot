"""Manager 测试的进程级框架状态隔离"""

from collections.abc import Generator

import nonebot
import pytest
from nonebot.internal.driver import Driver


@pytest.fixture(autouse=True)
def reset_nonebot_driver(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """避免 NoneBot Driver 与 Adapter 在应用工厂测试之间复用旧配置"""
    monkeypatch.setattr(nonebot, '_driver', None)
    Driver._adapters.clear()
    yield
