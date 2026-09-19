"""Worker 实例配置和进程生命周期"""

import asyncio
import socket
from collections.abc import Callable
from pathlib import Path

from kiribot.clients.process import ProcessClient
from kiribot.models.gateway import GatewayConfig
from kiribot.models.instances import (
    InstancesConfig,
    WorkerInstanceConfig,
    WorkerInstanceStatus,
)


class InstanceNotFoundError(KeyError):
    """请求的实例不存在"""


class InstanceAlreadyRunningError(RuntimeError):
    """实例已经运行"""


class InstanceNotRunningError(RuntimeError):
    """实例当前未运行"""


class InvalidInstanceConfigError(ValueError):
    """实例配置无法用于当前 Gateway"""


class InstanceService:
    """验证实例配置，并确保 Worker 仅由 Manager 创建和回收"""

    def __init__(
        self,
        config: InstancesConfig,
        gateway_config: GatewayConfig,
        gateway_token: str,
        gateway_host: str,
        gateway_port: int,
        process_client: ProcessClient | None = None,
        port_allocator: Callable[[], int] | None = None,
    ) -> None:
        self.config = config
        self.gateway_config = gateway_config
        self.gateway_token = gateway_token
        self.gateway_host = self._normalize_host(gateway_host)
        self.gateway_port = gateway_port
        self.process_client = process_client or ProcessClient()
        self._port_allocator = port_allocator or self._allocate_port
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._lock = asyncio.Lock()
        self._validate_config()

    @classmethod
    def from_config_file(
        cls,
        path: Path,
        gateway_config: GatewayConfig,
        gateway_token: str,
        gateway_host: str,
        gateway_port: int,
        process_client: ProcessClient | None = None,
        port_allocator: Callable[[], int] | None = None,
    ) -> InstanceService:
        try:
            content = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            config = InstancesConfig()
        else:
            config = InstancesConfig.model_validate_json(content)
        return cls(
            config,
            gateway_config,
            gateway_token,
            gateway_host,
            gateway_port,
            process_client,
            port_allocator,
        )

    def list(self) -> list[WorkerInstanceStatus]:
        """返回全部实例的最新进程状态"""
        return [self.get(instance_id) for instance_id in self.config.instances]

    def get(self, instance_id: str) -> WorkerInstanceStatus:
        """返回一个实例的最新进程状态"""
        instance = self._get_config(instance_id)
        process = self._processes.get(instance_id)
        running = process is not None and process.returncode is None
        if process is not None and not running:
            self._processes.pop(instance_id, None)
        return WorkerInstanceStatus(
            instance_id=instance_id,
            name=instance.name,
            implementation=instance.implementation,
            connection=instance.connection,
            running=running,
            pid=process.pid if process is not None and running else None,
        )

    async def start(self, instance_id: str) -> WorkerInstanceStatus:
        """由 Manager 启动实例并注入 Gateway 连接环境变量"""
        async with self._lock:
            return await self._start_unlocked(instance_id)

    async def stop(self, instance_id: str) -> WorkerInstanceStatus:
        """停止一个由当前 Manager 启动的实例"""
        async with self._lock:
            return await self._stop_unlocked(instance_id)

    async def restart(self, instance_id: str) -> WorkerInstanceStatus:
        """停止并重新启动一个正在运行的实例"""
        async with self._lock:
            await self._stop_unlocked(instance_id)
            return await self._start_unlocked(instance_id)

    async def start_auto_instances(self) -> None:
        """启动配置为随 Manager 启动的实例"""
        for instance_id, instance in self.config.instances.items():
            if instance.auto_start:
                await self.start(instance_id)

    async def close(self) -> None:
        """停止全部仍在运行的 Worker"""
        async with self._lock:
            processes = list(self._processes.values())
            self._processes.clear()
        await asyncio.gather(
            *(self.process_client.stop(process) for process in processes)
        )

    def _get_config(self, instance_id: str) -> WorkerInstanceConfig:
        try:
            return self.config.instances[instance_id]
        except KeyError as error:
            raise InstanceNotFoundError(instance_id) from error

    async def _start_unlocked(self, instance_id: str) -> WorkerInstanceStatus:
        current = self.get(instance_id)
        if current.running:
            raise InstanceAlreadyRunningError(instance_id)
        instance = self._get_config(instance_id)
        environment = {
            'KIRIBOT_WORKER_GATEWAY_URL': self._gateway_url(instance_id, instance),
            'KIRIBOT_WORKER_ACCESS_TOKEN': self.gateway_token,
            'KIRIBOT_WORKER_PORT': str(self._port_allocator()),
        }
        process = await self.process_client.start(
            instance.command,
            instance.working_directory,
            environment,
        )
        self._processes[instance_id] = process
        return self.get(instance_id)

    async def _stop_unlocked(self, instance_id: str) -> WorkerInstanceStatus:
        self._get_config(instance_id)
        process = self._processes.get(instance_id)
        if process is None or process.returncode is not None:
            self._processes.pop(instance_id, None)
            raise InstanceNotRunningError(instance_id)
        await self.process_client.stop(process)
        self._processes.pop(instance_id, None)
        return self.get(instance_id)

    def _validate_config(self) -> None:
        for instance_id, instance in self.config.instances.items():
            connection = self.gateway_config.connections.get(instance.connection)
            if connection is None:
                raise InvalidInstanceConfigError(
                    f'实例 {instance_id} 引用了不存在的 Gateway 连接 {instance.connection}'
                )
            if connection.protocol != 'onebot_v11':
                raise InvalidInstanceConfigError(
                    f'实例 {instance_id} 当前只支持 OneBot v11 连接'
                )
            if not instance.working_directory.is_dir():
                raise InvalidInstanceConfigError(
                    f'实例 {instance_id} 的工作目录不存在: {instance.working_directory}'
                )

    def _gateway_url(self, instance_id: str, instance: WorkerInstanceConfig) -> str:
        return (
            f'ws://{self.gateway_host}:{self.gateway_port}/gateway/internal/'
            f'{instance_id}/{instance.connection}/onebot/v11/ws'
        )

    @staticmethod
    def _normalize_host(host: str) -> str:
        if host == '0.0.0.0':
            return '127.0.0.1'
        if host == '::':
            return '[::1]'
        if ':' in host:
            return f'[{host}]'
        return host

    @staticmethod
    def _allocate_port() -> int:
        """请求系统分配一个当前可用的本地监听端口"""
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            return listener.getsockname()[1]
