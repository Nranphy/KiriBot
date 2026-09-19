"""健康接口及响应模型"""

from typing import Literal

from nonebot.params import Depends
from nonebot_plugin_alconna import Alconna, UniMessage, on_alconna
from pydantic import BaseModel

from kiribot.controller.admin import router
from kiribot.controller.admin.dependencies import depend_superadmin


class HealthResponse(BaseModel):
    """Manager 健康状态"""

    status: Literal["ok"] = "ok"


@router.get('/health', response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


health_command = on_alconna(Alconna('health'), use_cmd_start=True)


@health_command.handle()
async def handle_health(
    _permission: None = Depends(depend_superadmin),
) -> None:
    """响应跨平台 Bot 健康命令"""
    await UniMessage.text('KiriBot Manager 运行正常').finish()
