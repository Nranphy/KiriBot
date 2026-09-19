"""Worker 实例配置与状态模型"""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkerInstanceConfig(BaseModel):
    """一个由 Manager 管理的 NoneBot2 Worker 实例"""

    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1)
    implementation: Literal['nonebot2'] = 'nonebot2'
    working_directory: Path
    command: list[str] = Field(min_length=1)
    connection: str = Field(min_length=1)
    auto_start: bool = True


class InstancesConfig(BaseModel):
    """以稳定实例 ID 登记 Worker"""

    model_config = ConfigDict(extra='forbid')

    instances: dict[str, WorkerInstanceConfig] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_instance_ids(self) -> InstancesConfig:
        for instance_id in self.instances:
            if re.fullmatch(r'[A-Za-z0-9_-]+', instance_id) is None:
                raise ValueError('实例 ID 仅允许英文、数字、横线和下划线')
            if instance_id in {'manager', 'internal'}:
                raise ValueError('实例 ID 不能使用保留名称 manager/internal')
        return self


class WorkerInstanceStatus(BaseModel):
    """管理入口可读取的 Worker 运行状态"""

    instance_id: str
    name: str
    implementation: Literal['nonebot2']
    connection: str
    running: bool
    pid: int | None = None
