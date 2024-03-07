"""
API implementation
"""

import logging

from fastapi import APIRouter

from . import spec

logger = logging.getLogger(__name__)


class DefaultApi(spec.Api):
    """
    Implementation of the service API
    """

    async def echo(self, request: str) -> spec.EchoResponse:
        if request == "error":
            raise spec.EchoError()
        return spec.EchoResponse(text=f"{request}")


def api_router() -> APIRouter:
    return spec.make_router(DefaultApi())
