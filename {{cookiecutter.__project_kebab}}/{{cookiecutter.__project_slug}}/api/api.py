from fastapi import APIRouter
import abc
from . import spec


class AppState(abc.ABC):
    """
    State of the application
    """

    def counter(self) -> int:
        raise NotImplementedError()


class DefaultApi(spec.Api):
    """
    Implementation of the service API
    """

    @staticmethod
    async def echo(request: str) -> spec.EchoResponse:
        if request == "error":
            raise spec.EchoError()
        return spec.EchoResponse(text=f"{request}")


def router() -> APIRouter:
    return spec.make_router(DefaultApi)
