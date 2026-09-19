"""应用工厂与生命周期"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import nonebot
from fastapi import FastAPI
from loguru import logger
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter
from nonebot.adapters.satori import Adapter as SatoriAdapter

from kiribot.controller.admin import router as admin_router
from kiribot.controller.gateway import router as gateway_router
from kiribot.controller.loader import load_controllers
from kiribot.infra.config import Settings, get_settings
from kiribot.infra.log import configure_logging
from kiribot.infra.playwright import check_playwright
from kiribot.services.gateway import GatewayService, get_gateway_service
from kiribot.services.instances import InstanceService, get_instance_service


def initialize_nonebot(settings: Settings, gateway: GatewayService) -> FastAPI:
    """初始化 NoneBot 及协议 Adapter，返回其 ASGI 应用"""
    gateway_host = settings.host
    if gateway_host in {'0.0.0.0', '::'}:
        gateway_host = '127.0.0.1' if gateway_host == '0.0.0.0' else '[::1]'
    elif ':' in gateway_host:
        gateway_host = f'[{gateway_host}]'
    onebot_clients = {
        f'ws://{gateway_host}:{settings.port}/gateway/internal/manager/{name}/onebot/v11/ws'
        for name, config in gateway.config.connections.items()
        if config.protocol == 'onebot_v11'
    }
    satori_clients = [
        {
            'host': gateway_host,
            'port': settings.port,
            'path': f'gateway/internal/manager/{name}/satori',
            'token': gateway.internal_token,
        }
        for name, config in gateway.config.connections.items()
        if config.protocol == 'satori' and config.mode == 'forward'
    ]
    nonebot.init(
        _env_file=(),
        driver='~fastapi+~httpx+~websockets',
        log_level=settings.log_level,
        command_start={'/'},
        onebot_v11_ws_urls=onebot_clients,
        onebot_v11_access_token=gateway.internal_token,
        satori_clients=satori_clients,
    )
    driver = nonebot.get_driver()
    for adapter in (OneBotAdapter, SatoriAdapter):
        driver.register_adapter(adapter)
    bot_app: FastAPI = nonebot.get_asgi()
    return bot_app


def initialize_fastapi(
    settings: Settings,
    bot_app: FastAPI,
    gateway: GatewayService,
    instances: InstanceService,
) -> FastAPI:
    """初始化 FastAPI，并装配浏览器检查与 Bot 生命周期"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        configure_logging(settings.log_level)
        logger.info("正在检查 Playwright 无头浏览器")
        await check_playwright(settings.playwright_timeout)
        logger.info("启动检查通过，Manager 已就绪")
        try:
            await gateway.start()
            await instances.start_auto_instances()
            async with bot_app.router.lifespan_context(bot_app):
                yield
        finally:
            await instances.close()
            await gateway.close()
            logger.info("Manager 已关闭")

    return FastAPI(
        title='KiriBot Manager',
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )


def create_app() -> FastAPI:
    """组装日志、Web 与 Bot 应用及健康入口"""
    settings = get_settings()
    configure_logging(settings.log_level)
    gateway = get_gateway_service()
    instances = get_instance_service()
    bot_app = initialize_nonebot(settings, gateway)
    load_controllers()
    app = initialize_fastapi(settings, bot_app, gateway, instances)
    app.include_router(admin_router)
    app.include_router(gateway_router)
    app.mount('/manager', bot_app)
    return app
