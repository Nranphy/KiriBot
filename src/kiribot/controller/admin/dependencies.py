"""Manager 机器人命令的 NoneBot 依赖适配"""

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Event as OneBotEvent
from nonebot.adapters.onebot.v11 import GroupMessageEvent as OneBotGroupMessageEvent
from nonebot.adapters.satori.event import Event as SatoriEvent
from nonebot_plugin_alconna import UniMessage

from kiribot.models.users import ChatPlatform
from kiribot.services.permissions import PermissionDeniedError, get_permission_service


async def depend_superadmin(event: Event) -> None:
    """将聊天事件身份适配为权限服务调用，并转换拒绝结果"""
    platform, open_group_id, open_channel_id = _event_context(event)
    if platform is None:
        await UniMessage.text('权限不足').finish()
        return
    try:
        await get_permission_service().require_superadmin(
            platform=platform,
            open_user_id=event.get_user_id(),
            open_group_id=open_group_id,
            open_channel_id=open_channel_id,
        )
    except PermissionDeniedError:
        await UniMessage.text('权限不足').finish()


def _event_context(
    event: Event,
) -> tuple[ChatPlatform | None, str | None, str | None]:
    if isinstance(event, OneBotGroupMessageEvent):
        return ChatPlatform.QQ, str(event.group_id), None
    if isinstance(event, OneBotEvent):
        return ChatPlatform.QQ, None, None
    if isinstance(event, SatoriEvent):
        try:
            platform = ChatPlatform(event.login.platform)
        except ValueError:
            return None, None, None
        open_group_id = event.guild.id if event.guild is not None else None
        return platform, open_group_id, None
    return None, None, None
