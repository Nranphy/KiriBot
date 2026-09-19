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


@router.get('/instances/{instance_id}', response_model=WorkerInstanceStatus)
async def get_instance_status(
    instance_id: Annotated[str, Path(min_length=1)],
    service: Annotated[InstanceService, Depends(get_instance_service)],
) -> WorkerInstanceStatus:
    try:
        return service.get(instance_id)
    except InstanceNotFoundError as error:
        raise HTTPException(status_code=404, detail='Worker 实例不存在') from error


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


@router.post('/instances/{instance_id}/restart', response_model=WorkerInstanceStatus)
async def restart_instance(
    instance_id: Annotated[str, Path(min_length=1)],
    service: Annotated[InstanceService, Depends(get_instance_service)],
) -> WorkerInstanceStatus:
    try:
        return await service.restart(instance_id)
    except InstanceNotFoundError as error:
        raise HTTPException(status_code=404, detail='Worker 实例不存在') from error
    except InstanceNotRunningError as error:
        raise HTTPException(status_code=409, detail='Worker 实例未运行') from error


instance_command = on_alconna(
    Alconna(
        'instance',
        Subcommand('list'),
        Subcommand('status', Args['instance_id', str]),
        Subcommand('start', Args['instance_id', str]),
        Subcommand('stop', Args['instance_id', str]),
        Subcommand('restart', Args['instance_id', str]),
    ),
    use_cmd_start=True,
)


@instance_command.handle()
async def handle_instance(result: Arparma) -> None:
    """通过机器人命令查询或控制 Worker"""
    service = get_instance_service()
    action: Literal['list', 'status', 'start', 'stop', 'restart']
    if result.find('list'):
        action = 'list'
    elif result.find('status'):
        action = 'status'
    elif result.find('start'):
        action = 'start'
    elif result.find('stop'):
        action = 'stop'
    elif result.find('restart'):
        action = 'restart'
    else:
        await UniMessage.text(
            '请使用 instance list，或指定 status/start/stop/restart 和实例 ID'
        ).finish()
        return

    if action == 'list':
        statuses = service.list()
        message = '\n'.join(
            f'{status.instance_id}: {"运行中" if status.running else "已停止"}'
            for status in statuses
        )
        await UniMessage.text(message or '没有配置 Worker 实例').finish()
        return

    instance_id = result.all_matched_args['instance_id']
    try:
        if action == 'status':
            status = service.get(instance_id)
        elif action == 'start':
            status = await service.start(instance_id)
        elif action == 'stop':
            status = await service.stop(instance_id)
        else:
            status = await service.restart(instance_id)
    except InstanceNotFoundError:
        await UniMessage.text('Worker 实例不存在').finish()
        return
    except InstanceAlreadyRunningError:
        await UniMessage.text('Worker 实例已经运行').finish()
        return
    except InstanceNotRunningError:
        await UniMessage.text('Worker 实例未运行').finish()
        return
    if action == 'status':
        state = '运行中' if status.running else '已停止'
        pid = f'，PID {status.pid}' if status.pid is not None else ''
        await UniMessage.text(f'Worker {status.instance_id}：{state}{pid}').finish()
        return
    state = {
        'start': '已启动',
        'stop': '已停止',
        'restart': '已重启',
    }[action]
    await UniMessage.text(f'Worker {status.instance_id} {state}').finish()
