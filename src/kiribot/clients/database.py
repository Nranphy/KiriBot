"""Manager 数据库生命周期、持久化表和用户数据访问"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from kiribot.infra.config import get_settings
from kiribot.models.permissions import PermissionType
from kiribot.models.users import UserObservation


class Base(DeclarativeBase):
    """Manager 管理数据的声明式 ORM 基类"""


class UserTable(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime())
    updated_at: Mapped[datetime] = mapped_column(DateTime())


class IdentityTable(Base):
    __tablename__ = 'identities'

    platform: Mapped[str] = mapped_column(String(32), primary_key=True)
    open_user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime())
    updated_at: Mapped[datetime] = mapped_column(DateTime())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime())


class GroupTable(Base):
    __tablename__ = 'groups'
    __table_args__ = (
        Index(
            'uq_groups_platform_open_ids',
            'platform',
            'open_group_id',
            text("coalesce(open_channel_id, '')"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    open_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    open_channel_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime())
    updated_at: Mapped[datetime] = mapped_column(DateTime())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime())


class UserPermissionTable(Base):
    __tablename__ = 'user_permissions'

    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'),
        primary_key=True,
    )
    permission_type: Mapped[PermissionType] = mapped_column(
        Enum(
            PermissionType,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            name='permission_type',
        ),
        primary_key=True,
    )
    group_ids: Mapped[str | None] = mapped_column(Text())
    expired_at: Mapped[datetime | None] = mapped_column(DateTime())
    created_at: Mapped[datetime] = mapped_column(DateTime())
    updated_at: Mapped[datetime] = mapped_column(DateTime())


class DatabaseClient:
    """管理异步 SQLAlchemy Engine、Session 和首版表初始化"""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def start(self) -> None:
        """准备 SQLite 文件目录并幂等创建当前管理表"""
        url = make_url(self.url)
        if url.get_backend_name() != 'sqlite':
            raise ValueError('当前仅支持 SQLite 数据库')
        database_path = url.database
        if database_path is not None and database_path not in {'', ':memory:'}:
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """提供由调用方定义业务边界的数据库事务"""
        async with self.sessions() as session, session.begin():
            yield session

    async def close(self) -> None:
        await self.engine.dispose()


class UserRepository:
    """封装用户、平台身份与群聊记录的数据访问"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, observation: UserObservation) -> None:
        platform = observation.platform.value
        observed_at = observation.observed_at.astimezone(UTC).replace(tzinfo=None)
        identity = await self.session.get(
            IdentityTable,
            (platform, observation.open_user_id),
        )
        if identity is None:
            user = UserTable(
                created_at=observed_at,
                updated_at=observed_at,
            )
            self.session.add(user)
            await self.session.flush()
            identity = IdentityTable(
                platform=platform,
                open_user_id=observation.open_user_id,
                user_id=user.id,
                name=observation.name,
                created_at=observed_at,
                updated_at=observed_at,
                last_seen_at=observed_at,
            )
            self.session.add(identity)
        else:
            if observed_at >= identity.last_seen_at:
                if observation.name is not None:
                    identity.name = observation.name
                identity.updated_at = observed_at
                identity.last_seen_at = observed_at
            user = await self.session.get(UserTable, identity.user_id)
            if user is not None and observed_at > user.updated_at:
                user.updated_at = observed_at

        if observation.group is not None:
            await self._record_group(observation)

    async def _record_group(self, observation: UserObservation) -> None:
        group_observation = observation.group
        if group_observation is None:
            return
        observed_at = observation.observed_at.astimezone(UTC).replace(tzinfo=None)
        statement = select(GroupTable).where(
            GroupTable.platform == group_observation.platform.value,
            GroupTable.open_group_id == group_observation.open_group_id,
            GroupTable.open_channel_id == group_observation.open_channel_id,
        )
        group = await self.session.scalar(statement)
        if group is None:
            self.session.add(
                GroupTable(
                    platform=group_observation.platform.value,
                    open_group_id=group_observation.open_group_id,
                    open_channel_id=group_observation.open_channel_id,
                    name=group_observation.name,
                    created_at=observed_at,
                    updated_at=observed_at,
                    last_seen_at=observed_at,
                )
            )
            return
        if observed_at >= group.last_seen_at:
            if group_observation.name is not None:
                group.name = group_observation.name
            group.updated_at = observed_at
            group.last_seen_at = observed_at


@lru_cache
def get_database_client() -> DatabaseClient:
    """返回当前 Manager 进程共享的数据库 Client"""
    return DatabaseClient(get_settings().database_url)
