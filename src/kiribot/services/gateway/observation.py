"""Gateway 用户观察提交边界"""

from typing import Protocol

from kiribot.models.users import UserObservation


class UserObservationSink(Protocol):
    def submit(self, observation: UserObservation) -> bool:
        """提交观察，无法接收时返回 False"""
        raise NotImplementedError
