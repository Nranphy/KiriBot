"""Manager 运行资源的启动顺序与清理"""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from kiribot.clients.database import get_database_client
from kiribot.infra.config import Settings
from kiribot.infra.log import configure_logging
from kiribot.infra.playwright import check_playwright
from kiribot.services.gateway import get_gateway_service
from kiribot.services.instances import get_instance_service
from kiribot.services.users import get_user_recorder


@asynccontextmanager
async def manager_lifespan(app: FastAPI, *, bot_app: FastAPI, settings: Settings) -> AsyncGenerator[None, None]:
    """按依赖顺序启动共享资源，退出或启动失败时逆序清理"""
    configure_logging(settings.log_level)
    logger.info('正在检查 Playwright 无头浏览器')
    await check_playwright(settings.playwright_timeout)
    services = (
        get_database_client(),
        get_user_recorder(),
        get_gateway_service(),
        get_instance_service(),
    )
    async with AsyncExitStack() as stack:
        for service in services:
            # 先登记清理，以便启动中途失败时释放已取得的资源。
            stack.push_async_callback(service.close)
            await service.start()
        await stack.enter_async_context(bot_app.router.lifespan_context(bot_app))
        logger.info('启动检查通过，Manager 已就绪')
        yield
    logger.info('Manager 已关闭')
