"""验证权限配置、群聊范围、过期和多权限优先级"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from kiribot.clients.database import (
    DatabaseClient,
    GroupTable,
    IdentityTable,
    UserPermissionTable,
)
from kiribot.controller.app import create_app
from kiribot.models.permissions import PermissionsConfig, PermissionType
from kiribot.models.users import ChatPlatform, GroupObservation, UserObservation
from kiribot.services.permissions import (
    GroupNotFoundError,
    InvalidPermissionScopeError,
    PermissionDeniedError,
    PermissionService,
    get_permission_service,
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


def test_permission_management_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = DatabaseClient(
        f"sqlite+aiosqlite:///{(tmp_path / 'permission-routes.db').as_posix()}"
    )

    async def prepare() -> int:
        await database.start()
        await UserService(database).record(
            UserObservation(
                platform=ChatPlatform.QQ,
                open_user_id='10001',
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                group=GroupObservation(ChatPlatform.QQ, '20001'),
            )
        )
        async with database.sessions() as session:
            group_id = await session.scalar(select(GroupTable.id))
        assert group_id is not None
        return group_id

    group_id = asyncio.run(prepare())
    service = PermissionService(database)
    monkeypatch.setattr('kiribot.controller.app.check_playwright', AsyncMock())
    app = create_app()
    app.dependency_overrides[get_permission_service] = lambda: service
    try:
        with TestClient(app) as client:
            initial = client.get('/permissions/qq/10001')
            granted = client.put(
                '/permissions/qq/10001/ADMIN',
                json={
                    'group_ids': [group_id],
                    'expired_at': '2027-01-01T00:00:00+08:00',
                },
            )
            listed = client.get('/permissions/qq/10001')
            invalid_time = client.put(
                '/permissions/qq/10001/ADMIN',
                json={'expired_at': '2027-01-01T00:00:00'},
            )
            revoked = client.delete('/permissions/qq/10001/ADMIN')
            missing_record = client.delete('/permissions/qq/10001/ADMIN')
            missing_user = client.get('/permissions/qq/unknown')
    finally:
        asyncio.run(database.close())

    assert initial.status_code == 200
    assert initial.json()['global_permission'] == 'USER'
    assert initial.json()['permissions'] == []
    assert granted.status_code == 200
    assert granted.json()['permission_type'] == 'ADMIN'
    assert granted.json()['group_ids'] == [group_id]
    assert listed.json()['permissions'] == [granted.json()]
    assert invalid_time.status_code == 422
    assert revoked.status_code == 204
    assert missing_record.status_code == 404
    assert missing_record.json() == {'detail': '权限记录不存在'}
    assert missing_user.status_code == 404
    assert missing_user.json() == {'detail': '用户身份不存在'}


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

        record = await permissions.grant_identity(
            ChatPlatform.QQ,
            '10001',
            PermissionType.ADMIN,
            {group_ids[1], group_ids[0]},
        )
        assert record.group_ids == frozenset(group_ids)
        overview = await permissions.list_identity_permissions(
            ChatPlatform.QQ,
            '10001',
        )
        assert overview.user_id == user_id
        assert overview.global_permission is PermissionType.USER
        assert overview.permissions == [record]
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

        assert await permissions.revoke_identity(
            ChatPlatform.QQ,
            '10001',
            PermissionType.BANNED,
        )
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
        assert (
            await superadmin.get_identity_permission(
                ChatPlatform.QQ,
                '10001',
            )
            is PermissionType.SUPERADMIN
        )
        await superadmin.require_superadmin(ChatPlatform.QQ, '10001')
        with pytest.raises(PermissionDeniedError):
            await superadmin.require_superadmin(ChatPlatform.QQ, 'unknown')
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
