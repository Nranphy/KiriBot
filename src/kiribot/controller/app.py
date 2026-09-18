"""应用工厂与生命周期"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import nonebot
from fastapi import FastAPI
from loguru import logger
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter
from nonebot.adapters.satori import Adapter as SatoriAdapter

from kiribot.controller.admin.health import (
    create_health_router,
)
from kiribot.controller.gateway import router as gateway_router
from kiribot.infra.config import Settings
from kiribot.infra.log import configure_logging
from kiribot.infra.playwright import check_playwright
from kiribot.services.gateway import Gateway


def initialize_nonebot(settings: Settings) -> FastAPI:
    """初始化 NoneBot 及协议 Adapter，返回其 ASGI 应用"""
    nonebot.init(
        _env_file=(),
        driver='~fastapi+~httpx+~websockets',
        log_level=settings.log_level,
        command_start={'/'},
        onebot_v11_ws_urls=set(),
        satori_clients=[],
    )
    driver = nonebot.get_driver()
    for adapter in (OneBotAdapter, SatoriAdapter):
        driver.register_adapter(adapter)
    bot_app: FastAPI = nonebot.get_asgi()
    return bot_app


def initialize_fastapi(settings: Settings, bot_app: FastAPI, gateway: Gateway) -> FastAPI:
    """初始化 FastAPI，并装配浏览器检查与 Bot 生命周期"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        configure_logging(settings.log_level)
        logger.info("正在检查 Playwright 无头浏览器")
        await check_playwright(settings.playwright_timeout)
        logger.info("启动检查通过，Manager 已就绪")
        try:
            async with bot_app.router.lifespan_context(bot_app):
                yield
        finally:
            await gateway.close()
            logger.info("Manager 已关闭")

    return FastAPI(
        title='KiriBot Manager',
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """组装日志、Web 与 Bot 应用及健康入口"""
    settings = settings if settings is not None else Settings()
    configure_logging(settings.log_level)
    bot_app = initialize_nonebot(settings)
    host = settings.host
    if host in {'0.0.0.0', '::'}:
        host = '127.0.0.1' if host == '0.0.0.0' else '[::1]'
    elif ':' in host:
        host = f'[{host}]'
    gateway = Gateway.from_config_file(
        settings.gateway_config_path,
        manager_url=f'ws://{host}:{settings.port}/manager/onebot/v11/ws',
    )
    app = initialize_fastapi(settings, bot_app, gateway)
    app.state.gateway = gateway
    app.include_router(create_health_router())
    app.include_router(gateway_router)
    app.mount('/manager', bot_app)
    return app
