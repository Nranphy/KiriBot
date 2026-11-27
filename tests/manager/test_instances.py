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


@pytest.fixture(autouse=True)
def instance_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def create_service(tmp_path: Path) -> tuple[InstanceService, FakeProcessClient]:
    (tmp_path / "instances" / "echo-instance").mkdir(parents=True)
    config = InstancesConfig.model_validate(
        {
            "instances": {
                "echo-instance": {
                    "name": "Echo Instance",
                    "command": ["uv", "run", "python", "src/main.py"],
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
                    "platform": "qq",
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
async def test_manager_starts_instance_with_gateway_environment(tmp_path: Path) -> None:
    service, process_client = create_service(tmp_path)

    status = await service.start("echo-instance")

    assert status.running
    assert status.pid == 31415
    process_client.start_mock.assert_awaited_once_with(
        ["uv", "run", "python", "src/main.py"],
        tmp_path / "instances" / "echo-instance",
        {
            "KIRIBOT_INSTANCE_GATEWAY_URL": (
                "ws://127.0.0.1:8000/gateway/internal/"
                "echo-instance/napcat-1/onebot/v11/ws"
            ),
            "KIRIBOT_INSTANCE_GATEWAY_TOKEN": "runtime-secret",
            "KIRIBOT_INSTANCE_PORT": "18080",
            "KIRIBOT_INSTANCE_MANAGER_URL": "http://127.0.0.1:8000",
            "KIRIBOT_INSTANCE_MANAGER_TOKEN": service._tokens["echo-instance"],
        },
    )

    with pytest.raises(InstanceAlreadyRunningError):
        await service.start("echo-instance")

    stopped = await service.stop("echo-instance")
    assert not stopped.running
    process_client.stop_mock.assert_awaited_once()

    with pytest.raises(InstanceNotRunningError):
        await service.stop("echo-instance")


@pytest.mark.asyncio
async def test_close_stops_managed_instances(tmp_path: Path) -> None:
    service, process_client = create_service(tmp_path)
    await service.start("echo-instance")

    await service.close()

    process_client.stop_mock.assert_awaited_once()
    assert not service.get("echo-instance").running


@pytest.mark.asyncio
async def test_stopping_exited_instance_clears_credentials(tmp_path: Path) -> None:
    service, process_client = create_service(tmp_path)
    await service.start("echo-instance")
    process = cast(FakeProcess, process_client.start_mock.return_value)
    process.returncode = 1
    with pytest.raises(InstanceNotRunningError):
        await service.stop("echo-instance")
    assert "echo-instance" not in service._tokens
    process_client.stop_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_running_instance(tmp_path: Path) -> None:
    service, process_client = create_service(tmp_path)
    await service.start("echo-instance")

    status = await service.restart("echo-instance")

    assert status.running
    assert process_client.start_mock.await_count == 2
    process_client.stop_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_restart_rejects_stopped_instance(tmp_path: Path) -> None:
    service, process_client = create_service(tmp_path)

    with pytest.raises(InstanceNotRunningError):
        await service.restart("echo-instance")

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

    with TestClient(
        create_app(), headers={"Authorization": "Bearer test-admin-token"}
    ) as client:
        assert client.get("/instances").json() == []
        response = client.post("/instances/missing/start")

    assert response.status_code == 404
    assert response.json() == {"detail": "Instance 不存在"}


def test_instance_status_and_lifecycle_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kiribot.controller.app.check_playwright", AsyncMock())
    service, process_client = create_service(tmp_path)
    app = create_app()
    app.dependency_overrides[get_instance_service] = lambda: service

    with TestClient(
        app, headers={"Authorization": "Bearer test-admin-token"}
    ) as client:
        stopped = client.get("/instances/echo-instance")
        started = client.post("/instances/echo-instance/start")
        restarted = client.post("/instances/echo-instance/restart")
        stopped_again = client.post("/instances/echo-instance/stop")
        restart_stopped = client.post("/instances/echo-instance/restart")

    assert stopped.status_code == 200
    assert not stopped.json()["running"]
    assert started.json()["running"]
    assert restarted.json()["running"]
    assert not stopped_again.json()["running"]
    assert restart_stopped.status_code == 409
    assert restart_stopped.json() == {"detail": "Instance 未运行"}
    assert process_client.start_mock.await_count == 2
