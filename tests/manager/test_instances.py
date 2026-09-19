import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from kiribot.clients.process import ProcessClient
from kiribot.controller.app import create_app
from kiribot.models.gateway import GatewayConfig
from kiribot.models.instances import InstancesConfig
from kiribot.services.instances import (
    InstanceAlreadyRunningError,
    InstanceNotRunningError,
    InstanceService,
    get_instance_service,
)


class FakeProcess:
    pid = 31415
    returncode: int | None = None


class FakeProcessClient(ProcessClient):
    def __init__(self) -> None:
        self.start_mock = AsyncMock(
            return_value=cast(asyncio.subprocess.Process, FakeProcess())
        )
        self.stop_mock = AsyncMock()

    async def start(
        self,
        command: Sequence[str],
        working_directory: Path,
        environment: Mapping[str, str],
    ) -> asyncio.subprocess.Process:
        return await self.start_mock(command, working_directory, environment)

    async def stop(
        self,
        process: asyncio.subprocess.Process,
        timeout: float = 10,
    ) -> None:
        await self.stop_mock(process, timeout)


def create_service(tmp_path: Path) -> tuple[InstanceService, FakeProcessClient]:
    config = InstancesConfig.model_validate(
        {
            "instances": {
                "echo-worker": {
                    "name": "Echo Worker",
                    "working_directory": str(tmp_path),
                    "command": ["uv", "run", "python", "-m", "kiribot_worker"],
                    "connection": "napcat-1",
                    "auto_start": False,
                }
            }
        }
    )
    gateway_config = GatewayConfig.model_validate(
        {
            "connections": {
                "napcat-1": {
                    "protocol": "onebot_v11",
                    "mode": "reverse",
                }
            }
        }
    )
    process_client = FakeProcessClient()
    service = InstanceService(
        config,
        gateway_config,
        "runtime-secret",
        "0.0.0.0",
        8000,
        process_client,
        lambda: 18080,
    )
    return service, process_client


@pytest.mark.asyncio
async def test_manager_starts_worker_with_gateway_environment(tmp_path: Path) -> None:
    service, process_client = create_service(tmp_path)

    status = await service.start("echo-worker")

    assert status.running
    assert status.pid == 31415
    process_client.start_mock.assert_awaited_once_with(
        ["uv", "run", "python", "-m", "kiribot_worker"],
        tmp_path,
        {
            "KIRIBOT_WORKER_GATEWAY_URL": (
                "ws://127.0.0.1:8000/gateway/internal/"
                "echo-worker/napcat-1/onebot/v11/ws"
            ),
            "KIRIBOT_WORKER_ACCESS_TOKEN": "runtime-secret",
            "KIRIBOT_WORKER_PORT": "18080",
        },
    )

    with pytest.raises(InstanceAlreadyRunningError):
        await service.start("echo-worker")

    stopped = await service.stop("echo-worker")
    assert not stopped.running
    process_client.stop_mock.assert_awaited_once()

    with pytest.raises(InstanceNotRunningError):
        await service.stop("echo-worker")


@pytest.mark.asyncio
async def test_close_stops_managed_workers(tmp_path: Path) -> None:
    service, process_client = create_service(tmp_path)
    await service.start("echo-worker")

    await service.close()

    process_client.stop_mock.assert_awaited_once()
    assert not service.get("echo-worker").running


@pytest.mark.asyncio
async def test_restart_running_worker(tmp_path: Path) -> None:
    service, process_client = create_service(tmp_path)
    await service.start("echo-worker")

    status = await service.restart("echo-worker")

    assert status.running
    assert process_client.start_mock.await_count == 2
    process_client.stop_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_restart_rejects_stopped_worker(tmp_path: Path) -> None:
    service, process_client = create_service(tmp_path)

    with pytest.raises(InstanceNotRunningError):
        await service.restart("echo-worker")

    process_client.start_mock.assert_not_awaited()
    process_client.stop_mock.assert_not_awaited()


def test_instance_management_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kiribot.controller.app.check_playwright", AsyncMock())
    monkeypatch.setenv(
        "KIRIBOT_GATEWAY_CONFIG_PATH", str(tmp_path / "missing-gateway.json")
    )
    monkeypatch.setenv(
        "KIRIBOT_INSTANCES_CONFIG_PATH", str(tmp_path / "missing-instances.json")
    )

    with TestClient(create_app()) as client:
        assert client.get("/instances").json() == []
        response = client.post("/instances/missing/start")

    assert response.status_code == 404
    assert response.json() == {"detail": "Worker 实例不存在"}


def test_instance_status_and_lifecycle_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kiribot.controller.app.check_playwright", AsyncMock())
    service, process_client = create_service(tmp_path)
    app = create_app()
    app.dependency_overrides[get_instance_service] = lambda: service

    with TestClient(app) as client:
        stopped = client.get("/instances/echo-worker")
        started = client.post("/instances/echo-worker/start")
        restarted = client.post("/instances/echo-worker/restart")
        stopped_again = client.post("/instances/echo-worker/stop")
        restart_stopped = client.post("/instances/echo-worker/restart")

    assert stopped.status_code == 200
    assert not stopped.json()["running"]
    assert started.json()["running"]
    assert restarted.json()["running"]
    assert not stopped_again.json()["running"]
    assert restart_stopped.status_code == 409
    assert restart_stopped.json() == {"detail": "Worker 实例未运行"}
    assert process_client.start_mock.await_count == 2
