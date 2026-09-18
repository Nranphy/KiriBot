"""健康接口及响应模型"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel


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
