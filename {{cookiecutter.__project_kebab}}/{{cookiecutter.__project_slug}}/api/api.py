"""
API implementation
"""

import abc
import logging

from fastapi import APIRouter

from . import spec

logger = logging.getLogger(__name__)


class AppState(abc.ABC):
    """
    State of the application
    """

    @abc.abstractmethod
    def counter(self) -> int:
        ...


class DefaultApi(spec.Api):
    """
    Implementation of the service API
    """

    @staticmethod
    async def echo(request: str) -> spec.EchoResponse:
        if request == "error":
            raise spec.EchoError()
        return spec.EchoResponse(text=f"{request}")


def api_router() -> APIRouter:
    return spec.make_router(DefaultApi)
