"""启动 Manager"""

import uvicorn

from kiribot.controller.app import create_app
from kiribot.infra.config import get_settings
from kiribot.infra.log import configure_logging

if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        create_app(),
        host=settings.host,
        port=settings.port,
        log_config=None,
        log_level=settings.log_level.lower(),
    )
