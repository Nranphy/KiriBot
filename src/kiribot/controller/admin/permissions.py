"""用户权限的 Web 与 Bot 管理入口"""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Response, status
from nonebot.params import Depends as NoneBotDepends
from nonebot_plugin_alconna import (
    Alconna,
    AlconnaMatch,
    Args,
    Match,
    Option,
    Subcommand,
    UniMessage,
    on_alconna,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict

from kiribot.controller.admin import router
from kiribot.controller.admin.dependencies import depend_superadmin
from kiribot.models.permissions import (
    IdentityPermissions,
    PermissionRecord,
    PermissionType,
)
from kiribot.models.users import ChatPlatform
from kiribot.services.permissions import (
    GroupNotFoundError,
    InvalidPermissionScopeError,
    PermissionService,
    UserNotFoundError,
    get_permission_service,
)


class GrantPermissionRequest(BaseModel):
    """Web 授权请求"""

    model_config = ConfigDict(extra='forbid')

    group_ids: set[int] | None = None
    expired_at: AwareDatetime | None = None


@router.get(
    '/permissions/{platform}/{open_user_id}',
    response_model=IdentityPermissions,
)
async def get_identity_permissions(
    platform: ChatPlatform,
    open_user_id: Annotated[str, Path(min_length=1)],
    service: Annotated[PermissionService, Depends(get_permission_service)],
) -> IdentityPermissions:
    try:
        return await service.list_identity_permissions(platform, open_user_id)
    except UserNotFoundError as error:
        raise HTTPException(status_code=404, detail='用户身份不存在') from error


@router.put(
    '/permissions/{platform}/{open_user_id}/{permission_type}',
    response_model=PermissionRecord,
)
async def grant_identity_permission(
    platform: ChatPlatform,
    open_user_id: Annotated[str, Path(min_length=1)],
    permission_type: PermissionType,
    request: GrantPermissionRequest,
    service: Annotated[PermissionService, Depends(get_permission_service)],
) -> PermissionRecord:
    try:
        return await service.grant_identity(
            platform,
            open_user_id,
            permission_type,
            request.group_ids,
            request.expired_at,
        )
    except UserNotFoundError as error:
        raise HTTPException(status_code=404, detail='用户身份不存在') from error
    except GroupNotFoundError as error:
        raise HTTPException(status_code=404, detail='群聊不存在') from error
    except InvalidPermissionScopeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete(
    '/permissions/{platform}/{open_user_id}/{permission_type}',
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_identity_permission(
    platform: ChatPlatform,
    open_user_id: Annotated[str, Path(min_length=1)],
    permission_type: PermissionType,
    service: Annotated[PermissionService, Depends(get_permission_service)],
) -> Response:
    try:
        revoked = await service.revoke_identity(
            platform,
            open_user_id,
            permission_type,
        )
    except UserNotFoundError as error:
        raise HTTPException(status_code=404, detail='用户身份不存在') from error
    if not revoked:
        raise HTTPException(status_code=404, detail='权限记录不存在')
    return Response(status_code=status.HTTP_204_NO_CONTENT)


permission_command = on_alconna(
    Alconna(
        'permission',
        Subcommand(
            'list',
            Args['platform', str]['open_user_id', str],
        ),
        Subcommand(
            'grant',
            Args['platform', str]['open_user_id', str]['permission_type', str],
            Option('--groups', Args['group_ids', str]),
            Option('--expires', Args['expired_at', str]),
        ),
        Subcommand(
            'revoke',
            Args['platform', str]['open_user_id', str]['permission_type', str],
        ),
    ),
    use_cmd_start=True,
)


@permission_command.assign('$main')
async def handle_permission_help(
    _permission: None = NoneBotDepends(depend_superadmin),
) -> None:
    await UniMessage.text(
        '请使用 permission list、grant 或 revoke；grant 可附加 --groups ID,ID 和 --expires ISO时间'
    ).finish()


@permission_command.assign('list')
async def handle_permission_list(
    platform: Match[str] = AlconnaMatch('platform'),
    open_user_id: Match[str] = AlconnaMatch('open_user_id'),
    _permission: None = NoneBotDepends(depend_superadmin),
    service: PermissionService = NoneBotDepends(get_permission_service),
) -> None:
    try:
        result = await service.list_identity_permissions(
            _parse_platform(platform.result),
            open_user_id.result,
        )
    except (UserNotFoundError, ValueError) as error:
        await _finish_permission_error(error)
        return
    await UniMessage.text(_format_identity_permissions(result)).finish()


@permission_command.assign('grant')
async def handle_permission_grant(
    platform: Match[str] = AlconnaMatch('platform'),
    open_user_id: Match[str] = AlconnaMatch('open_user_id'),
    permission_type: Match[str] = AlconnaMatch('permission_type'),
    group_ids: Match[str] = AlconnaMatch('group_ids'),
    expired_at: Match[str] = AlconnaMatch('expired_at'),
    _permission: None = NoneBotDepends(depend_superadmin),
    service: PermissionService = NoneBotDepends(get_permission_service),
) -> None:
    try:
        record = await service.grant_identity(
            _parse_platform(platform.result),
            open_user_id.result,
            _parse_permission_type(permission_type.result),
            _parse_group_ids(group_ids.result) if group_ids.available else None,
            _parse_expired_at(expired_at.result) if expired_at.available else None,
        )
    except (
        GroupNotFoundError,
        InvalidPermissionScopeError,
        UserNotFoundError,
        ValueError,
    ) as error:
        await _finish_permission_error(error)
        return
    await UniMessage.text(f'已授予 {_format_permission_record(record)}').finish()


@permission_command.assign('revoke')
async def handle_permission_revoke(
    platform: Match[str] = AlconnaMatch('platform'),
    open_user_id: Match[str] = AlconnaMatch('open_user_id'),
    permission_type: Match[str] = AlconnaMatch('permission_type'),
    _permission: None = NoneBotDepends(depend_superadmin),
    service: PermissionService = NoneBotDepends(get_permission_service),
) -> None:
    try:
        parsed_permission = _parse_permission_type(permission_type.result)
        revoked = await service.revoke_identity(
            _parse_platform(platform.result),
            open_user_id.result,
            parsed_permission,
        )
    except (UserNotFoundError, ValueError) as error:
        await _finish_permission_error(error)
        return
    if not revoked:
        await UniMessage.text('权限记录不存在').finish()
        return
    await UniMessage.text(f'已撤销 {parsed_permission.value}').finish()


def _parse_platform(value: str) -> ChatPlatform:
    try:
        return ChatPlatform(value.lower())
    except ValueError as error:
        raise ValueError('不支持的平台') from error


def _parse_permission_type(value: str) -> PermissionType:
    try:
        return PermissionType(value.upper())
    except ValueError as error:
        raise ValueError('无效的权限类型') from error


def _parse_group_ids(value: str) -> set[int]:
    try:
        group_ids = {int(group_id) for group_id in value.split(',')}
    except ValueError as error:
        raise ValueError('群聊 ID 必须是逗号分隔的整数') from error
    if not group_ids:
        raise ValueError('群聊 ID 不能为空')
    return group_ids


def _parse_expired_at(value: str) -> datetime:
    try:
        expired_at = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError('过期时间必须使用 ISO 8601 格式') from error
    if expired_at.tzinfo is None:
        raise ValueError('过期时间必须包含时区')
    return expired_at


async def _finish_permission_error(error: Exception) -> None:
    if isinstance(error, UserNotFoundError):
        message = '用户身份不存在'
    elif isinstance(error, GroupNotFoundError):
        message = '群聊不存在'
    else:
        message = str(error)
    await UniMessage.text(message).finish()


def _format_identity_permissions(result: IdentityPermissions) -> str:
    user_id = str(result.user_id) if result.user_id is not None else '未记录'
    lines = [
        f'{result.platform.value}:{result.open_user_id}（用户 {user_id}）',
        f'全局最终权限：{result.global_permission.value}',
    ]
    if not result.permissions:
        lines.append('数据库权限：无')
    else:
        lines.extend(f'- {_format_permission_record(record)}' for record in result.permissions)
    return '\n'.join(lines)


def _format_permission_record(record: PermissionRecord) -> str:
    groups = (
        ','.join(str(group_id) for group_id in sorted(record.group_ids)) if record.group_ids is not None else '全局'
    )
    expired_at = record.expired_at.isoformat() if record.expired_at is not None else '永久'
    return f'{record.permission_type.value}（群聊：{groups}；过期：{expired_at}）'
