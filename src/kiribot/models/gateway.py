"""Gateway 外部服务登记配置"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExternalConnectionConfig(BaseModel):
    """外部连接配置"""

    model_config = ConfigDict(extra='forbid')
    protocol: Literal['onebot_v11', 'satori']
    """外部服务使用的协议"""

    mode: Literal['reverse', 'forward'] = 'reverse'
    """连接方向：反向由外部服务连接 Gateway，正向由 Gateway 连接外部服务"""

    token: str | None = Field(default=None, repr=False)
    """外部连接的鉴权令牌，未配置时不校验令牌，且不在模型 repr 中显示"""

    self_id: str | None = Field(default=None, min_length=1)
    """可选的账号限制，配置后仅接受该账号连接；字符串不能为空"""

    url: str | None = None
    """正向连接的外部服务地址，正向模式必须提供，反向模式无需配置"""

    @model_validator(mode='after')
    def validate_address(self) -> ExternalConnectionConfig:
        """正向服务必须登记地址，实际接入尚未实现"""
        if self.mode == 'forward' and not self.url:
            raise ValueError('正向连接必须提供 url')
        return self


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
