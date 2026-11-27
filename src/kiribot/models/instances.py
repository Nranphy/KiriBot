"""Instance 配置与状态模型"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InstanceConfig(BaseModel):
    """一个由 Manager 管理的 NoneBot2 Instance"""

    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1)
    implementation: Literal['nonebot2'] = 'nonebot2'
    command: list[str] = Field(min_length=1)
    connection: str = Field(min_length=1)
    auto_start: bool = True


class InstancesConfig(BaseModel):
    """以稳定 Instance ID 登记 Instance"""

    model_config = ConfigDict(extra='forbid')

    instances: dict[str, InstanceConfig] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_instance_ids(self) -> InstancesConfig:
        for instance_id in self.instances:
            if re.fullmatch(r'[A-Za-z0-9_-]+', instance_id) is None:
                raise ValueError('Instance ID 仅允许英文、数字、横线和下划线')
            if instance_id in {'manager', 'internal'}:
                raise ValueError('Instance ID 不能使用保留名称 manager/internal')
        return self


class InstanceStatus(BaseModel):
    """管理入口可读取的 Instance 运行状态"""

    instance_id: str
    name: str
    implementation: Literal['nonebot2']
    connection: str
    running: bool
    pid: int | None = None
