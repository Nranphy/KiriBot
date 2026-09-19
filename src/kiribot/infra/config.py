"""加载应用配置"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """读取当前工作目录的 .env，环境变量优先"""

    model_config = SettingsConfigDict(
        env_prefix="KIRIBOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    host: str = Field(default="127.0.0.1", min_length=1)
    """HTTP 服务监听地址，默认仅允许本机访问"""

    port: int = Field(default=8000, ge=1, le=65535)
    """HTTP 服务监听端口，范围为 1 至 65535"""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    """控制台日志的最低输出级别，同时用于 Loguru 和 Uvicorn"""

    playwright_timeout: float = Field(default=30, gt=0, le=300)
    """启动时无头浏览器检查的总超时秒数，必须大于零且不超过 300"""

    gateway_config_path: Path = Path("config/gateway.json")
    """Gateway JSON 配置路径，相对路径基于工作目录"""

    database_url: str = Field(
        default="sqlite+aiosqlite:///data/kiribot.db",
        min_length=1,
        repr=False,
    )
    """SQLAlchemy 异步数据库连接 URL，当前仅支持 SQLite"""

    instances_config_path: Path = Path("config/instances.json")
    """Worker 实例 JSON 配置路径，相对路径基于工作目录"""

    permissions_config_path: Path = Path('config/permissions.json')
    """权限 JSON 配置路径，相对路径基于工作目录"""


@lru_cache
def get_settings() -> Settings:
    """返回当前 Manager 进程共享的配置"""
    return Settings()
