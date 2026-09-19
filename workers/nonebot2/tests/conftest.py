import nonebot
from nonebot.adapters.onebot.v11 import Adapter


def pytest_configure() -> None:
    """在收集插件测试前提供最小 NoneBot 环境"""
    nonebot.init(_env_file=(), driver="~fastapi+~httpx+~websockets")
    nonebot.get_driver().register_adapter(Adapter)
