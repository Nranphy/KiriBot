"""Worker 子进程生命周期封装"""

import asyncio
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path


class ProcessClient:
    """创建和终止由 Manager 持有的子进程"""

    async def start(
        self,
        command: Sequence[str],
        working_directory: Path,
        environment: Mapping[str, str],
    ) -> asyncio.subprocess.Process:
        child_environment = os.environ.copy()
        child_environment.update(environment)
        if os.name == 'nt':
            return await asyncio.create_subprocess_exec(
                *command,
                cwd=working_directory,
                env=child_environment,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        return await asyncio.create_subprocess_exec(
            *command,
            cwd=working_directory,
            env=child_environment,
            start_new_session=True,
        )

    async def stop(
        self,
        process: asyncio.subprocess.Process,
        timeout: float = 10,
    ) -> None:
        if process.returncode is not None:
            return
        if os.name == 'nt':
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except TimeoutError:
            if os.name == 'nt':
                killer = await asyncio.create_subprocess_exec(
                    'taskkill',
                    '/PID',
                    str(process.pid),
                    '/T',
                    '/F',
                )
                await killer.wait()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            if process.returncode is None:
                await process.wait()
