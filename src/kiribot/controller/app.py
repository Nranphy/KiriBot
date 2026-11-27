"""Manager 应用工厂"""

from functools import partial

from fastapi import FastAPI

from kiribot.controller.bot import initialize_nonebot
from kiribot.controller.lifespan import manager_lifespan
from kiribot.controller.loader import mount_controllers
from kiribot.infra.config import get_settings
from kiribot.infra.log import configure_logging


def create_app() -> FastAPI:
    """初始化两个应用，再挂载 Controller 与 Bot 子应用"""
    settings = get_settings()
    configure_logging(settings.log_level)
    bot_app = initialize_nonebot(settings)
    app = FastAPI(
        title='KiriBot Manager',
        lifespan=partial(manager_lifespan, bot_app=bot_app, settings=settings),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    mount_controllers(app)
    app.mount('/manager', bot_app)
    return app
