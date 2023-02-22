"""
Full API specification
"""

import abc
import enum
import inspect
from abc import abstractmethod
from contextlib import contextmanager
from functools import wraps
from typing import (
    Any,
    Callable,
    Generator,
    Generic,
    List,
    Tuple,
    Type,
    TypeVar,
    get_type_hints,
)

import fastapi
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRouter
from pydantic import BaseModel
from pydantic.generics import GenericModel


T = TypeVar("T")


ErrorVariants = TypeVar("ErrorVariants")


class UserError(GenericModel, Generic[ErrorVariants]):
    """
    Error model for all user errors.
    Provides reason of error and details
    """

    error: ErrorVariants
    detail: str


async def default_validation_exception_handler(
    _: fastapi.Request, exc: RequestValidationError
):
    """
    Handler for fastapi errors
    """
    return fastapi.Response(
        UserError(error=exc.__class__.__name__, detail=str(exc)).json(),
        headers={"Content-Type": "application/json"},
        status_code=422,
    )


def _create_error_enum(name: str, errors: List[Type[Exception]]):
    variants = dict()
    for error in errors:
        error_type = error.__name__
        variants[error_type] = error_type
    return enum.Enum(f"{name}_errors", variants, type=str)


def expect_exceptions(func: Callable, exceptions: Tuple[Type[Exception], ...]):
    """
    Specifies which exceptions can function raise
    Only those exceptions will be handled
    """

    @wraps(func)
    async def _handle_exceptions(*args: Any, **kwargs: Any):
        try:
            result = await func(*args, **kwargs)
            return result
        except exceptions as exc:
            return fastapi.Response(
                UserError(error=exc.__class__.__name__, detail=str(exc)).json(),
                headers={"Content-Type": "application/json"},
                status_code=getattr(exc, "status_code"),
            )

    errors_by_status_code = dict()

    for exception in exceptions:
        status_code = getattr(exception, "status_code")
        if status_code not in errors_by_status_code:
            errors_by_status_code[status_code] = list()
        errors_by_status_code[status_code].append(exception)

    additional_responses = dict()
    for status_code, errors in errors_by_status_code.items():
        additional_responses[status_code] = {
            "model": UserError[
                _create_error_enum(f"{func.__name__}{status_code}", errors)
            ]
        }

    additional_responses[422] = {
        "model": UserError[
            _create_error_enum(f"{func.__name__}422", [RequestValidationError])
        ]
    }

    _handle_exceptions.additional_responses = additional_responses

    return _handle_exceptions


class EchoResponse(BaseModel):
    text: str


class EchoError(Exception):
    status_code = 400


class Api(abc.ABC):
    """
    Api interface for implementation definition
    """

    @staticmethod
    @abstractmethod
    async def echo(request: str) -> EchoResponse:
        """
        Echo what user inputs.
        Raises error if request = 'error'
        """
        raise NotImplementedError()


class ApiSection:
    """
    Helper method for registering methids
    Registers methods in given router with specificed prefix and tag
    """

    def __init__(self, router: APIRouter, prefix: str, tag: str):
        self.router = router
        self.prefix = prefix
        self.tag = tag

    def register(
        self, method: str, path: str, endpoint: Any, *exceptions: Type[Exception]
    ):
        endpoint = expect_exceptions(endpoint, exceptions)
        response_model = get_type_hints(endpoint)["return"]

        if response_model == fastapi.Response:
            response_model = None

        additional_responses = getattr(endpoint, "additional_responses", None)

        path_with_prefix = self.prefix.rstrip("/") + ("/" if path else "") + path
        self.router.add_api_route(
            path_with_prefix,
            endpoint,
            methods=[method],
            tags=[self.tag],
            response_model=response_model,
            summary=inspect.getdoc(endpoint),
            description=None,
            responses=additional_responses,
        )


def make_router(api: type[Api]) -> APIRouter:  # pylint: disable=[R0915,]
    router = APIRouter()

    @contextmanager
    def section(prefix: str, tag: str) -> Generator[ApiSection, None, None]:
        yield ApiSection(router, prefix, tag)

    with section("/echo", "echo") as sec:
        sec.register("GET", "", api.echo, EchoError)

    return router
