"""Worker 实例 Web 与 Bot 管理入口"""

from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Path
from nonebot_plugin_alconna import (
    Alconna,
    Args,
    Arparma,
    Subcommand,
    UniMessage,
    on_alconna,
)

from kiribot.controller.admin import router
from kiribot.models.instances import WorkerInstanceStatus
from kiribot.services.instances import (
    InstanceAlreadyRunningError,
    InstanceNotFoundError,
    InstanceNotRunningError,
    InstanceService,
    get_instance_service,
)


@router.get('/instances', response_model=list[WorkerInstanceStatus])
async def list_instances(
    service: Annotated[InstanceService, Depends(get_instance_service)],
) -> list[WorkerInstanceStatus]:
    return service.list()


@router.post('/instances/{instance_id}/start', response_model=WorkerInstanceStatus)
async def start_instance(
    instance_id: Annotated[str, Path(min_length=1)],
    service: Annotated[InstanceService, Depends(get_instance_service)],
) -> WorkerInstanceStatus:
    try:
        return await service.start(instance_id)
    except InstanceNotFoundError as error:
        raise HTTPException(status_code=404, detail='Worker 实例不存在') from error
    except InstanceAlreadyRunningError as error:
        raise HTTPException(status_code=409, detail='Worker 实例已经运行') from error


@router.post('/instances/{instance_id}/stop', response_model=WorkerInstanceStatus)
async def stop_instance(
    instance_id: Annotated[str, Path(min_length=1)],
    service: Annotated[InstanceService, Depends(get_instance_service)],
) -> WorkerInstanceStatus:
    try:
        return await service.stop(instance_id)
    except InstanceNotFoundError as error:
        raise HTTPException(status_code=404, detail='Worker 实例不存在') from error
    except InstanceNotRunningError as error:
        raise HTTPException(status_code=409, detail='Worker 实例未运行') from error


instance_command = on_alconna(
    Alconna(
        'instance',
        Subcommand('list'),
        Subcommand('start', Args['instance_id', str]),
        Subcommand('stop', Args['instance_id', str]),
    ),
    use_cmd_start=True,
)


@instance_command.handle()
async def handle_instance(result: Arparma) -> None:
    """通过机器人命令查询、启动或停止 Worker"""
    service = get_instance_service()
    action: Literal['list', 'start', 'stop']
    if result.find('list'):
        action = 'list'
    elif result.find('start'):
        action = 'start'
    else:
        action = 'stop'

    if action == 'list':
        statuses = service.list()
        message = '\n'.join(f'{status.instance_id}: {"运行中" if status.running else "已停止"}' for status in statuses)
        await UniMessage.text(message or '没有配置 Worker 实例').finish()
        return

    instance_id = result.all_matched_args['instance_id']
    try:
        status = await service.start(instance_id) if action == 'start' else await service.stop(instance_id)
    except InstanceNotFoundError:
        await UniMessage.text('Worker 实例不存在').finish()
        return
    except InstanceAlreadyRunningError:
        await UniMessage.text('Worker 实例已经运行').finish()
        return
    except InstanceNotRunningError:
        await UniMessage.text('Worker 实例未运行').finish()
        return
    await UniMessage.text(f'Worker {status.instance_id} {"已启动" if status.running else "已停止"}').finish()
