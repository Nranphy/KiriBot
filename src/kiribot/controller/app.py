"""应用工厂与生命周期"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from kiribot.controller.admin.health import create_health_router
from kiribot.infra.config import Settings
from kiribot.infra.log import configure_logging
from kiribot.infra.playwright import check_playwright


def create_app(settings: Settings | None = None) -> FastAPI:
    """装配应用，浏览器检查通过后才提供服务"""
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        configure_logging(settings.log_level)
        logger.info("正在检查 Playwright 无头浏览器")
        await check_playwright(settings.playwright_timeout)
        logger.info("启动检查通过，Manager 已就绪")
        try:
            yield
        finally:
            logger.info("Manager 已关闭")

    app = FastAPI(
        title="KiriBot Manager",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(create_health_router())
    return app
