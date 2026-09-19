"""配置与数据库共同驱动的权限服务"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from kiribot.clients.database import (
    DatabaseClient,
    GroupTable,
    IdentityTable,
    UserPermissionTable,
    UserTable,
)
from kiribot.models.permissions import (
    PermissionIdentityConfig,
    PermissionRecord,
    PermissionsConfig,
    PermissionType,
)


class UserNotFoundError(LookupError):
    """目标用户不存在"""


class GroupNotFoundError(LookupError):
    """至少一个目标群聊不存在"""


class InvalidPermissionScopeError(ValueError):
    """权限群聊范围为空或格式无效"""


class PermissionService:
    """计算配置和数据库共同作用后的用户权限"""

    _priority = (
        PermissionType.BANNED,
        PermissionType.SUPERADMIN,
        PermissionType.ADMIN,
        PermissionType.USER,
    )

    def __init__(
        self,
        database: DatabaseClient,
        config: PermissionsConfig | None = None,
    ) -> None:
        self.database = database
        self.config = config if config is not None else PermissionsConfig()
        self.superadmins = self._identity_keys(self.config.superadmins)
        self.blacklist = self._identity_keys(self.config.blacklist)

    @classmethod
    def from_config_file(
        cls,
        database: DatabaseClient,
        path: Path,
    ) -> PermissionService:
        try:
            content = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            config = PermissionsConfig()
        else:
            config = PermissionsConfig.model_validate_json(content)
        return cls(database, config)

    async def get_active_permissions(
        self,
        user_id: int,
        group_id: int | None = None,
        at: datetime | None = None,
    ) -> set[PermissionType]:
        """返回指定时间和群聊上下文中生效的权限集合"""
        now = self._to_database_time(at if at is not None else datetime.now(UTC))
        async with self.database.sessions() as session:
            if await session.get(UserTable, user_id) is None:
                raise UserNotFoundError('用户不存在')
            identity_rows = await session.scalars(
                select(IdentityTable).where(IdentityTable.user_id == user_id)
            )
            identities = {
                (identity.platform, identity.open_user_id)
                for identity in identity_rows
            }
            if identities & self.blacklist:
                return {PermissionType.BANNED}
            if identities & self.superadmins:
                return {PermissionType.SUPERADMIN}

            permission_rows = await session.scalars(
                select(UserPermissionTable).where(
                    UserPermissionTable.user_id == user_id
                )
            )
            active = {
                row.permission_type
                for row in permission_rows
                if self._is_active(row, group_id, now)
            }
        return active or {PermissionType.USER}

    async def get_effective_permission(
        self,
        user_id: int,
        group_id: int | None = None,
        at: datetime | None = None,
    ) -> PermissionType:
        """按固定优先级返回当前上下文的最终权限"""
        active = await self.get_active_permissions(user_id, group_id, at)
        return next(permission for permission in self._priority if permission in active)

    async def grant(
        self,
        user_id: int,
        permission_type: PermissionType,
        group_ids: set[int] | None = None,
        expired_at: datetime | None = None,
    ) -> PermissionRecord:
        """新增或覆盖用户的同类型权限"""
        normalized_group_ids = self._normalize_group_ids(group_ids)
        normalized_expired_at = (
            self._to_database_time(expired_at) if expired_at is not None else None
        )
        now = self._to_database_time(datetime.now(UTC))
        async with self.database.transaction() as session:
            if await session.get(UserTable, user_id) is None:
                raise UserNotFoundError('用户不存在')
            if normalized_group_ids is not None:
                existing_group_ids = set(
                    await session.scalars(
                        select(GroupTable.id).where(
                            GroupTable.id.in_(normalized_group_ids)
                        )
                    )
                )
                if existing_group_ids != normalized_group_ids:
                    raise GroupNotFoundError('至少一个群聊不存在')
            row = await session.get(
                UserPermissionTable,
                (user_id, permission_type),
            )
            serialized_group_ids = self._serialize_group_ids(normalized_group_ids)
            if row is None:
                row = UserPermissionTable(
                    user_id=user_id,
                    permission_type=permission_type,
                    group_ids=serialized_group_ids,
                    expired_at=normalized_expired_at,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.group_ids = serialized_group_ids
                row.expired_at = normalized_expired_at
                row.updated_at = now
        return PermissionRecord(
            user_id=user_id,
            permission_type=permission_type,
            group_ids=(
                frozenset(normalized_group_ids)
                if normalized_group_ids is not None
                else None
            ),
            expired_at=normalized_expired_at,
        )

    async def revoke(
        self,
        user_id: int,
        permission_type: PermissionType,
    ) -> bool:
        """删除指定类型权限，不存在时返回 False"""
        async with self.database.transaction() as session:
            row = await session.get(
                UserPermissionTable,
                (user_id, permission_type),
            )
            if row is None:
                return False
            await session.delete(row)
            return True

    @staticmethod
    def _identity_keys(
        identities: list[PermissionIdentityConfig],
    ) -> set[tuple[str, str]]:
        return {
            (identity.platform.value, identity.open_user_id)
            for identity in identities
        }

    @staticmethod
    def _normalize_group_ids(group_ids: set[int] | None) -> set[int] | None:
        if group_ids is None:
            return None
        if not group_ids or any(group_id <= 0 for group_id in group_ids):
            raise InvalidPermissionScopeError('群聊范围必须包含有效的内部群聊 ID')
        return set(group_ids)

    @staticmethod
    def _serialize_group_ids(group_ids: set[int] | None) -> str | None:
        if group_ids is None:
            return None
        return ','.join(str(group_id) for group_id in sorted(group_ids))

    @staticmethod
    def _parse_group_ids(group_ids: str) -> set[int]:
        return {int(group_id) for group_id in group_ids.split(',')}

    @classmethod
    def _is_active(
        cls,
        row: UserPermissionTable,
        group_id: int | None,
        now: datetime,
    ) -> bool:
        if row.expired_at is not None and now >= row.expired_at:
            return False
        if row.group_ids is None:
            return True
        return group_id is not None and group_id in cls._parse_group_ids(row.group_ids)

    @staticmethod
    def _to_database_time(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError('时间必须包含时区')
        return value.astimezone(UTC).replace(tzinfo=None)
