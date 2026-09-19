"""NoneBot2 与 Manager Gateway 的连接配置"""

from typing import Literal

import nonebot
from nonebot.adapters.onebot.v11 import Adapter
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """读取由 Manager 启动子进程时注入的 Worker 配置"""

    model_config = SettingsConfigDict(
        env_prefix='KIRIBOT_WORKER_',
        extra='ignore',
    )

    gateway_url: str = Field(min_length=1)
    """Gateway 提供的 OneBot v11 内部 WebSocket 地址"""

    access_token: str = Field(min_length=1)
    """Manager 为本次运行生成的 Gateway 内部 Token"""

    host: str = Field(default='127.0.0.1', min_length=1)
    """NoneBot Driver 监听地址"""

    port: int = Field(default=0, ge=0, le=65535)
    """NoneBot Driver 监听端口，默认由系统分配以避免实例冲突"""

    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO'
    """NoneBot 日志等级"""


def initialize_nonebot(settings: WorkerSettings) -> None:
    """初始化 NoneBot2，并注册 OneBot v11 Adapter"""
    nonebot.init(
        _env_file=(),
        driver='~fastapi+~httpx+~websockets',
        log_level=settings.log_level,
        command_start={'/'},
        onebot_v11_ws_urls={settings.gateway_url},
        onebot_v11_access_token=settings.access_token,
    )
    nonebot.get_driver().register_adapter(Adapter)
