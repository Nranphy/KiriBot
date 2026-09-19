"""从 Satori 事件提取用户与群聊观察"""

from datetime import UTC, datetime

from kiribot.models.users import ChatPlatform, GroupObservation, UserObservation


def extract_user_observation(
    body: dict,
    platform: ChatPlatform,
) -> UserObservation | None:
    """从包含 user 的 Satori EVENT 生成平台观察"""
    event_platform = body.get('platform')
    if event_platform is not None and event_platform != platform.value:
        raise ValueError('Satori 事件平台与 Gateway 配置不一致')
    user = body.get('user')
    if not isinstance(user, dict):
        return None
    open_user_id = user.get('id')
    if not isinstance(open_user_id, str | int) or isinstance(open_user_id, bool):
        return None

    group = _extract_group(body, platform)
    event_time = body.get('timestamp')
    observed_at = (
        datetime.fromtimestamp(event_time / 1000, UTC)
        if isinstance(event_time, int | float) and not isinstance(event_time, bool)
        else datetime.now(UTC)
    )
    return UserObservation(
        platform=platform,
        open_user_id=str(open_user_id),
        observed_at=observed_at,
        name=_optional_string(user.get('name')),
        group=group,
    )


def _extract_group(body: dict, platform: ChatPlatform) -> GroupObservation | None:
    guild = body.get('guild')
    if not isinstance(guild, dict):
        return None
    open_group_id = guild.get('id')
    if not isinstance(open_group_id, str | int) or isinstance(open_group_id, bool):
        return None
    return GroupObservation(
        platform=platform,
        open_group_id=str(open_group_id),
        name=_optional_string(guild.get('name')),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
