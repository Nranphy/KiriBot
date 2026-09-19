"""Echo 命令"""

from nonebot_plugin_alconna import (
    Alconna,
    Args,
    Match,
    MultiVar,
    UniMessage,
    on_alconna,
)

echo_command = on_alconna(
    Alconna('echo', Args['content', MultiVar(str)]),
    use_cmd_start=True,
)


def render_echo(content: tuple[str, ...]) -> str:
    """使用空格还原 Alconna 解析出的多段文本"""
    return ' '.join(content)


@echo_command.handle()
async def handle_echo(content: Match[tuple[str, ...]]) -> None:
    """回显命令参数"""
    await UniMessage.text(render_echo(content.result)).finish()
