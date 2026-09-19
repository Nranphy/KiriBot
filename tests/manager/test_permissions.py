"""验证权限配置、群聊范围、过期和多权限优先级"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from kiribot.clients.database import (
    DatabaseClient,
    GroupTable,
    IdentityTable,
    UserPermissionTable,
)
from kiribot.models.permissions import PermissionsConfig, PermissionType
from kiribot.models.users import ChatPlatform, GroupObservation, UserObservation
from kiribot.services.permissions import (
    GroupNotFoundError,
    InvalidPermissionScopeError,
    PermissionService,
)
from kiribot.services.users import UserService


def test_permissions_config_rejects_duplicates_and_conflicts(tmp_path: Path) -> None:
    missing = tmp_path / 'missing.json'
    service = PermissionService.from_config_file(
        DatabaseClient('sqlite+aiosqlite:///:memory:'),
        missing,
    )
    assert service.config == PermissionsConfig()
    assert not missing.exists()

    with pytest.raises(ValidationError, match='重复身份'):
        PermissionsConfig.model_validate(
            {
                'superadmins': [
                    {'platform': 'qq', 'open_user_id': '1'},
                    {'platform': 'qq', 'open_user_id': '1'},
                ]
            }
        )
    with pytest.raises(ValidationError, match='不能同时'):
        PermissionsConfig.model_validate(
            {
                'superadmins': [{'platform': 'qq', 'open_user_id': '1'}],
                'blacklist': [{'platform': 'qq', 'open_user_id': '1'}],
            }
        )


@pytest.mark.asyncio
async def test_grants_multiple_scoped_permissions_and_resolves_priority(
    tmp_path: Path,
) -> None:
    database, user_id, group_ids = await _prepare_database(tmp_path)
    permissions = PermissionService(database)
    now = datetime(2026, 1, 2, tzinfo=UTC)
    try:
        assert (
            await permissions.get_effective_permission(user_id, group_ids[0], now)
            is PermissionType.USER
        )

        record = await permissions.grant(
            user_id,
            PermissionType.ADMIN,
            {group_ids[1], group_ids[0]},
        )
        assert record.group_ids == frozenset(group_ids)
        assert (
            await permissions.get_effective_permission(user_id, group_ids[0], now)
            is PermissionType.ADMIN
        )
        assert (
            await permissions.get_effective_permission(user_id, None, now)
            is PermissionType.USER
        )

        await permissions.grant(
            user_id,
            PermissionType.BANNED,
            {group_ids[0]},
            now + timedelta(hours=1),
        )
        assert (
            await permissions.get_effective_permission(user_id, group_ids[0], now)
            is PermissionType.BANNED
        )
        assert (
            await permissions.get_effective_permission(
                user_id,
                group_ids[0],
                now + timedelta(hours=2),
            )
            is PermissionType.ADMIN
        )

        async with database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(UserPermissionTable)
                )
                == 2
            )
            admin = await session.get(
                UserPermissionTable,
                (user_id, PermissionType.ADMIN),
            )
            assert admin is not None
            assert admin.group_ids == ','.join(str(group_id) for group_id in group_ids)

        assert await permissions.revoke(user_id, PermissionType.BANNED)
        assert not await permissions.revoke(user_id, PermissionType.BANNED)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_config_permissions_override_database(tmp_path: Path) -> None:
    database, user_id, group_ids = await _prepare_database(tmp_path)
    try:
        superadmin = PermissionService(
            database,
            PermissionsConfig.model_validate(
                {
                    'superadmins': [
                        {'platform': 'qq', 'open_user_id': '10001'}
                    ]
                }
            ),
        )
        await superadmin.grant(user_id, PermissionType.BANNED)
        assert (
            await superadmin.get_effective_permission(user_id, group_ids[0])
            is PermissionType.SUPERADMIN
        )

        blacklist = PermissionService(
            database,
            PermissionsConfig.model_validate(
                {
                    'blacklist': [
                        {'platform': 'qq', 'open_user_id': '10001'}
                    ]
                }
            ),
        )
        assert (
            await blacklist.get_effective_permission(user_id, group_ids[0])
            is PermissionType.BANNED
        )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_grant_validates_group_scope(tmp_path: Path) -> None:
    database, user_id, _ = await _prepare_database(tmp_path)
    permissions = PermissionService(database)
    try:
        with pytest.raises(InvalidPermissionScopeError):
            await permissions.grant(user_id, PermissionType.ADMIN, set())
        with pytest.raises(GroupNotFoundError):
            await permissions.grant(user_id, PermissionType.ADMIN, {999999})
    finally:
        await database.close()


async def _prepare_database(tmp_path: Path) -> tuple[DatabaseClient, int, list[int]]:
    database = DatabaseClient(
        f"sqlite+aiosqlite:///{(tmp_path / 'permissions.db').as_posix()}"
    )
    await database.start()
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)
    users = UserService(database)
    for group_id in ('20001', '20002'):
        await users.record(
            UserObservation(
                platform=ChatPlatform.QQ,
                open_user_id='10001',
                observed_at=observed_at,
                group=GroupObservation(ChatPlatform.QQ, group_id),
            )
        )
    async with database.sessions() as session:
        identity = await session.get(IdentityTable, ('qq', '10001'))
        assert identity is not None
        group_ids = list(await session.scalars(select(GroupTable.id).order_by(GroupTable.id)))
    return database, identity.user_id, group_ids
