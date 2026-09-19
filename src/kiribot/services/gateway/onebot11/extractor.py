"""从 OneBot 11 事件提取用户与群聊观察"""

from datetime import UTC, datetime

from kiribot.models.users import ChatPlatform, GroupObservation, UserObservation


def extract_user_observation(
    payload: dict,
    platform: ChatPlatform,
) -> UserObservation | None:
    """仅从带有明确发送者的消息事件生成观察"""
    if payload.get('post_type') != 'message':
        return None
    open_user_id = payload.get('user_id')
    if not isinstance(open_user_id, str | int) or isinstance(open_user_id, bool):
        return None

    sender = payload.get('sender')
    sender = sender if isinstance(sender, dict) else {}
    name = _optional_string(sender.get('card')) or _optional_string(sender.get('nickname'))
    group = None
    open_group_id = payload.get('group_id')
    if (
        payload.get('message_type') == 'group'
        and isinstance(open_group_id, str | int)
        and not isinstance(open_group_id, bool)
    ):
        group = GroupObservation(
            platform=platform,
            open_group_id=str(open_group_id),
        )
    event_time = payload.get('time')
    observed_at = (
        datetime.fromtimestamp(event_time, UTC)
        if isinstance(event_time, int | float) and not isinstance(event_time, bool)
        else datetime.now(UTC)
    )
    return UserObservation(
        platform=platform,
        open_user_id=str(open_user_id),
        observed_at=observed_at,
        name=name,
        group=group,
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
