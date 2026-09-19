"""Controller 模块加载入口"""

from importlib import import_module


def load_controllers() -> None:
    """在 NoneBot 初始化后加载声明式 Web 与 Bot Controller"""
    for module in (
        'kiribot.controller.admin.health',
        'kiribot.controller.admin.instances',
        'kiribot.controller.admin.permissions',
    ):
        import_module(module)
