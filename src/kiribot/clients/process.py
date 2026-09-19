"""Worker 子进程生命周期封装"""

import asyncio
import os
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
        return await asyncio.create_subprocess_exec(
            *command,
            cwd=working_directory,
            env=child_environment,
        )

    async def stop(
        self,
        process: asyncio.subprocess.Process,
        timeout: float = 10,
    ) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
