"""用户与群聊自动观察模型"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ChatPlatform(StrEnum):
    """当前支持的聊天平台"""

    QQ = 'qq'


@dataclass(frozen=True, slots=True)
class GroupObservation:
    """从外部事件观察到的群聊信息"""

    platform: ChatPlatform
    open_group_id: str
    open_channel_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class UserObservation:
    """从外部事件观察到的平台用户及会话信息"""

    platform: ChatPlatform
    open_user_id: str
    observed_at: datetime
    name: str | None = None
    group: GroupObservation | None = None
