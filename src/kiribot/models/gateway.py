"""Gateway 外部服务登记配置"""

import re
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AnyHttpUrl,
    AnyWebsocketUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def validate_absolute_url(value: object, schemes: set[str], name: str) -> object:
    """在 Pydantic 归一化前校验 URL 的绝对地址结构"""
    if not isinstance(value, str):
        return value
    parsed = urlsplit(value)
    if value != value.strip() or parsed.scheme not in schemes or not parsed.netloc:
        raise ValueError(f'{name} 必须是包含主机的绝对地址')
    return value


class ChatPlatform(StrEnum):
    """Gateway 当前允许登记的聊天平台"""

    QQ = 'qq'


class OneBot11ForwardConfig(BaseModel):
    """OneBot 11 Universal 正向连接配置"""

    model_config = ConfigDict(extra='forbid')
    protocol: Literal['onebot_v11']
    mode: Literal['forward']
    platform: ChatPlatform
    url: AnyWebsocketUrl
    token: str | None = Field(default=None, repr=False)
    self_id: str | None = Field(default=None, min_length=1)

    @field_validator('url', mode='before')
    @classmethod
    def validate_raw_url(cls, url: object) -> object:
        return validate_absolute_url(url, {'ws', 'wss'}, 'OneBot 11 url')


class OneBot11ReverseConfig(BaseModel):
    """OneBot 11 Universal 反向连接配置"""

    model_config = ConfigDict(extra='forbid')
    protocol: Literal['onebot_v11']
    mode: Literal['reverse']
    platform: ChatPlatform
    token: str | None = Field(default=None, repr=False)
    self_id: str | None = Field(default=None, min_length=1)


OneBot11ConnectionConfig = Annotated[
    OneBot11ForwardConfig | OneBot11ReverseConfig,
    Field(discriminator='mode'),
]


class SatoriForwardConfig(BaseModel):
    """Satori 标准正向连接配置"""

    model_config = ConfigDict(extra='forbid')
    protocol: Literal['satori']
    mode: Literal['forward'] = 'forward'
    platform: ChatPlatform
    url: AnyHttpUrl | AnyWebsocketUrl
    token: str | None = Field(default=None, repr=False)

    @field_validator('url', mode='before')
    @classmethod
    def validate_raw_url(cls, url: object) -> object:
        return validate_absolute_url(url, {'http', 'https', 'ws', 'wss'}, 'Satori url')

    @field_validator('url')
    @classmethod
    def validate_service_url(cls, url: AnyHttpUrl | AnyWebsocketUrl) -> AnyHttpUrl | AnyWebsocketUrl:
        """服务根地址不得夹带凭据、查询参数或片段"""
        if url.username is not None or url.password is not None:
            raise ValueError('Satori url 不能包含用户名或密码')
        if url.query is not None or url.fragment is not None:
            raise ValueError('Satori url 不能包含查询参数或片段')
        return url


ExternalConnectionConfig = Annotated[
    OneBot11ConnectionConfig | SatoriForwardConfig,
    Field(discriminator='protocol'),
]


class GatewayConfig(BaseModel):
    """以服务名称登记连接，空 JSON 对象表示没有外部服务"""

    model_config = ConfigDict(extra='forbid')
    connections: dict[str, ExternalConnectionConfig] = Field(default_factory=dict)
    """以外部服务名称为键的连接登记表，名称用于 WS 路由；默认为空"""

    @model_validator(mode='after')
    def validate_names(self) -> GatewayConfig:
        """连接名称必须是安全的 URL 路径段"""
        for name in self.connections:
            self._validate_name(name)
        return self

    @staticmethod
    def _validate_name(name: str) -> None:
        """检查名称格式并排除内部端点的保留名称"""
        if re.fullmatch(r'[A-Za-z0-9_-]+', name) is None:
            raise ValueError('连接名称不能为空，且仅允许英文、数字、横线和下划线')
        if name in {'manager', 'internal'}:
            raise ValueError('连接名称不能使用保留名称 manager/internal')
