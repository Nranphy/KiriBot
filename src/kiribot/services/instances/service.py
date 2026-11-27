"""Instance 配置和进程生命周期"""

import asyncio
import secrets
import socket
from collections.abc import Callable
from pathlib import Path

from kiribot.clients.process import ProcessClient
from kiribot.infra.network import gateway_url_host
from kiribot.models.gateway import GatewayConfig
from kiribot.models.instances import (
    InstancesConfig,
    InstanceConfig,
    InstanceStatus,
)


class InstanceNotFoundError(KeyError):
    """请求的 Instance 不存在"""


class InstanceAlreadyRunningError(RuntimeError):
    """Instance 已经运行"""


class InstanceNotRunningError(RuntimeError):
    """Instance 当前未运行"""


class InvalidInstanceConfigError(ValueError):
    """Instance 配置无法用于当前 Gateway"""


class InstanceService:
    """验证 Instance 配置，并确保 Instance 仅由 Manager 创建和回收"""

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
        self.gateway_host = gateway_url_host(gateway_host)
        self.gateway_port = gateway_port
        self.process_client = process_client or ProcessClient()
        self._port_allocator = port_allocator or self._allocate_port
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._tokens: dict[str, str] = {}
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

    def list(self) -> list[InstanceStatus]:
        """返回全部 Instance 的最新进程状态"""
        return [self.get(instance_id) for instance_id in self.config.instances]

    def get(self, instance_id: str) -> InstanceStatus:
        """返回一个 Instance 的最新进程状态"""
        instance = self._get_config(instance_id)
        process = self._processes.get(instance_id)
        running = process is not None and process.returncode is None
        if process is not None and not running:
            self._processes.pop(instance_id, None)
            self._tokens.pop(instance_id, None)
        return InstanceStatus(
            instance_id=instance_id,
            name=instance.name,
            connection=instance.connection,
            running=running,
            pid=process.pid if process is not None and running else None,
        )

    async def start_instance(self, instance_id: str) -> InstanceStatus:
        """由 Manager 启动 Instance 并注入 Gateway 连接环境变量"""
        async with self._lock:
            return await self._start_unlocked(instance_id)

    async def stop_instance(self, instance_id: str) -> InstanceStatus:
        """停止一个由当前 Manager 启动的 Instance"""
        async with self._lock:
            return await self._stop_unlocked(instance_id)

    async def restart_instance(self, instance_id: str) -> InstanceStatus:
        """停止并重新启动一个正在运行的 Instance"""
        async with self._lock:
            await self._stop_unlocked(instance_id)
            return await self._start_unlocked(instance_id)

    async def start(self) -> None:
        """启动配置为随 Manager 启动的 Instance"""
        for instance_id, instance in self.config.instances.items():
            if instance.auto_start:
                await self.start_instance(instance_id)

    async def close(self) -> None:
        """停止全部仍在运行的 Instance"""
        async with self._lock:
            processes = list(self._processes.values())
            self._processes.clear()
            self._tokens.clear()
        await asyncio.gather(
            *(self.process_client.stop(process) for process in processes)
        )

    def _get_config(self, instance_id: str) -> InstanceConfig:
        try:
            return self.config.instances[instance_id]
        except KeyError as error:
            raise InstanceNotFoundError(instance_id) from error

    def authenticate_instance(self, token: str) -> str | None:
        """仅接受仍在运行的 Instance 凭据，停止或重启即撤销旧凭据"""
        for instance_id, expected in list(self._tokens.items()):
            if secrets.compare_digest(token.encode(), expected.encode()):
                return instance_id if self.get(instance_id).running else None
        return None

    async def _start_unlocked(self, instance_id: str) -> InstanceStatus:
        current = self.get(instance_id)
        if current.running:
            raise InstanceAlreadyRunningError(instance_id)
        instance = self._get_config(instance_id)
        token = secrets.token_urlsafe(32)
        environment = {
            'KIRIBOT_INSTANCE_GATEWAY_URL': self._gateway_url(instance_id, instance),
            'KIRIBOT_INSTANCE_GATEWAY_TOKEN': self.gateway_token,
            'KIRIBOT_INSTANCE_PORT': str(self._port_allocator()),
            "KIRIBOT_INSTANCE_MANAGER_URL": f"http://{self.gateway_host}:{self.gateway_port}",
            "KIRIBOT_INSTANCE_MANAGER_TOKEN": token,
        }
        process = await self.process_client.start(
            instance.command,
            self._instance_directory(instance_id),
            environment,
        )
        self._processes[instance_id] = process
        self._tokens[instance_id] = token
        return self.get(instance_id)

    async def _stop_unlocked(self, instance_id: str) -> InstanceStatus:
        self._get_config(instance_id)
        process = self._processes.get(instance_id)
        if process is None or process.returncode is not None:
            self._processes.pop(instance_id, None)
            self._tokens.pop(instance_id, None)
            raise InstanceNotRunningError(instance_id)
        await self.process_client.stop(process)
        self._processes.pop(instance_id, None)
        self._tokens.pop(instance_id, None)
        return self.get(instance_id)

    def _validate_config(self) -> None:
        for instance_id, instance in self.config.instances.items():
            connection = self.gateway_config.external.get(instance.connection)
            if connection is None:
                raise InvalidInstanceConfigError(
                    f'Instance {instance_id} 引用了不存在的 Gateway 连接 {instance.connection}'
                )
            if connection.protocol != 'onebot_v11':
                raise InvalidInstanceConfigError(
                    f'Instance {instance_id} 当前只支持 OneBot v11 连接'
                )
            self._instance_directory(instance_id)

    @staticmethod
    def _instance_directory(instance_id: str) -> Path:
        """定位手动部署的目录，并校验符号链接的实际目标"""
        root = Path("instances").resolve()
        directory = (root / instance_id).resolve()
        if root not in directory.parents or not directory.is_dir():
            raise InvalidInstanceConfigError(
                f"Instance {instance_id} 需要 instances/ 下已存在的目录: {directory}"
            )
        return directory

    def _gateway_url(self, instance_id: str, instance: InstanceConfig) -> str:
        return (
            f'ws://{self.gateway_host}:{self.gateway_port}/gateway/internal/'
            f'{instance_id}/{instance.connection}/onebot/v11/ws'
        )

    @staticmethod
    def _allocate_port() -> int:
        """在 Instance 启动锁内请求一个当前可用的本地监听端口"""
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            return listener.getsockname()[1]
