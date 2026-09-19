"""Worker 启动入口"""

import nonebot

from kiribot_worker.connection import WorkerSettings, initialize_nonebot


def main() -> None:
    """初始化插件和 Adapter，并启动 Worker"""
    settings = WorkerSettings()  # pyright: ignore[reportCallIssue]
    initialize_nonebot(settings)
    nonebot.load_plugin('kiribot_worker.plugins.echo')
    nonebot.run(host=settings.host, port=settings.port)


if __name__ == '__main__':
    main()
