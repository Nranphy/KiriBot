"""健康接口及响应模型"""

from typing import Literal

from fastapi import APIRouter
from nonebot import on_command
from nonebot.matcher import Matcher
from pydantic import BaseModel

_health_matcher: type[Matcher] | None = None


class HealthResponse(BaseModel):
    """Manager 健康状态"""

    status: Literal["ok"] = "ok"


def create_health_router() -> APIRouter:
    """创建健康接口"""
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    return router


def register_health_command() -> None:
    """幂等注册 Manager 的 Bot 健康命令"""
    global _health_matcher

    if _health_matcher is not None:
        return

    matcher = on_command('health')

    @matcher.handle()
    async def handle_health() -> None:
        await matcher.finish('KiriBot Manager 运行正常')

    _health_matcher = matcher
