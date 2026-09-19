"""权限类型、配置和业务结果模型"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kiribot.models.users import ChatPlatform


class PermissionType(StrEnum):
    """KiriBot 集中管理的用户权限类型"""

    SUPERADMIN = 'SUPERADMIN'
    ADMIN = 'ADMIN'
    USER = 'USER'
    BANNED = 'BANNED'


class PermissionIdentityConfig(BaseModel):
    """权限配置文件中的平台身份"""

    model_config = ConfigDict(extra='forbid', frozen=True)

    platform: ChatPlatform
    open_user_id: str = Field(min_length=1)


class PermissionsConfig(BaseModel):
    """启动时加载的全局超级管理员和黑名单"""

    model_config = ConfigDict(extra='forbid')

    superadmins: list[PermissionIdentityConfig] = Field(default_factory=list)
    blacklist: list[PermissionIdentityConfig] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_identities(self) -> PermissionsConfig:
        superadmins = set(self.superadmins)
        blacklist = set(self.blacklist)
        if len(superadmins) != len(self.superadmins):
            raise ValueError('superadmins 中存在重复身份')
        if len(blacklist) != len(self.blacklist):
            raise ValueError('blacklist 中存在重复身份')
        if superadmins & blacklist:
            raise ValueError('同一身份不能同时属于 superadmins 和 blacklist')
        return self


class PermissionRecord(BaseModel):
    """权限服务返回的数据库权限记录"""

    user_id: int
    permission_type: PermissionType
    group_ids: frozenset[int] | None
    expired_at: datetime | None
