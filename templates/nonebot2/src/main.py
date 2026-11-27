"""Instance 启动入口"""

import nonebot

from connection import InstanceSettings, initialize_nonebot


def main() -> None:
    """初始化插件和 Adapter，并启动 Instance"""
    settings = InstanceSettings()  # pyright: ignore[reportCallIssue]
    initialize_nonebot(settings)
    nonebot.load_plugin('plugins.echo')
    nonebot.run()


if __name__ == '__main__':
    main()
