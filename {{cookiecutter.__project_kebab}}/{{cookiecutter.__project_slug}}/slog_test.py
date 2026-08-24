"""
tests for structured logging module (slog.py)
"""

import asyncio
import logging
import time
import uuid
from unittest.mock import ANY

import pytest
from opentelemetry.sdk.trace import TracerProvider

from .slog import logging_context
from .testing_utils import JsonLogs

logger = logging.getLogger("test_logger")


@pytest.fixture()
def freeze_time(monkeypatch: pytest.MonkeyPatch):
    def mock_time() -> float:
        return 1689083906744488000

    monkeypatch.setattr(time, "time_ns", mock_time)


@pytest.fixture()
def freeze_uuid(monkeypatch: pytest.MonkeyPatch):
    def mock_uuid4() -> uuid.UUID:
        return uuid.UUID("a4f3fc0f-3caf-4bc7-8a71-e19069248dc2")

    monkeypatch.setattr(uuid, "uuid4", mock_uuid4)


@pytest.mark.usefixtures("freeze_uuid", "freeze_time")
def test_structured_info(structured_logs_capture: JsonLogs):
    logger.info("test info")
    assert structured_logs_capture.parse() == [
        {
            "severity": "INFO",
            "message": "test info",
            "time": "2023-07-11T13:58:26.744488Z",
            "logger": "test_logger",
        }
    ]


@pytest.mark.usefixtures("freeze_uuid", "freeze_time")
def test_structured_warning(structured_logs_capture: JsonLogs):
    logger.warning("test warning")
    assert structured_logs_capture.parse() == [
        {
            "severity": "WARNING",
            "message": "test warning",
            "time": "2023-07-11T13:58:26.744488Z",
            "logger": "test_logger",
        }
    ]


@pytest.mark.usefixtures("freeze_uuid", "freeze_time")
def test_structured_error(structured_logs_capture: JsonLogs):
    try:
        raise ValueError()
    except ValueError:
        logger.exception("test exception")

    assert structured_logs_capture.parse() == [
        {
            "severity": "ERROR",
            "message": "test exception",
            "time": "2023-07-11T13:58:26.744488Z",
            "logger": "test_logger",
            "traceback": ANY,
        },
    ]


@pytest.mark.usefixtures("freeze_uuid", "freeze_time")
def test_structured_info_parametrized(structured_logs_capture: JsonLogs):
    logger.info("test extra", extra={"foo": "bar"})
    logger.info("test args: %s: %s", "foo", "bar")

    assert structured_logs_capture.parse() == [
        {
            "severity": "INFO",
            "message": "test extra",
            "time": "2023-07-11T13:58:26.744488Z",
            "logger": "test_logger",
            "foo": "bar",
        },
        {
            "severity": "INFO",
            "message": "test args: foo: bar",
            "time": "2023-07-11T13:58:26.744488Z",
            "logger": "test_logger",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("freeze_uuid", "freeze_time")
async def test_structured_info_context(structured_logs_capture: JsonLogs):
    async def task1():
        with logging_context(task_name="task1", a=20):
            await asyncio.sleep(0)
            logger.info("Hello from task 1")

    async def task2():
        with logging_context(task_name="task2", a=30):
            logger.info("Hello from task 2")
            await asyncio.sleep(0)

    with logging_context(parent="foo", a=10):
        await asyncio.gather(task1(), task2())
        logger.info("End tasks", extra={"a": 0, "b": 5})

    assert structured_logs_capture.parse()[0]["a"] == 30

    assert structured_logs_capture.parse() == [
        {
            "severity": "INFO",
            "message": "Hello from task 2",
            "time": "2023-07-11T13:58:26.744488Z",
            "logger": "test_logger",
            "parent": "foo",
            "task_name": "task2",
            "a": 30,
        },
        {
            "severity": "INFO",
            "message": "Hello from task 1",
            "time": "2023-07-11T13:58:26.744488Z",
            "logger": "test_logger",
            "parent": "foo",
            "task_name": "task1",
            "a": 20,
        },
        {
            "severity": "INFO",
            "message": "End tasks",
            "time": "2023-07-11T13:58:26.744488Z",
            "logger": "test_logger",
            "parent": "foo",
            "a": 0,
            "b": 5,
        },
    ]


@pytest.mark.usefixtures("freeze_uuid", "freeze_time")
def test_structured_info_non_serializable(structured_logs_capture: JsonLogs):
    class NotSerializable:
        def __str__(self) -> str:
            return "i am not serializable"

    obj = NotSerializable()

    # This should not raise, non-serializable values are stringified via str()
    logger.info("test non serializable", extra={"obj": obj})

    assert structured_logs_capture.parse() == [
        {
            "severity": "INFO",
            "message": "test non serializable",
            "time": "2023-07-11T13:58:26.744488Z",
            "logger": "test_logger",
            "obj": "i am not serializable",
        }
    ]


@pytest.mark.usefixtures("freeze_uuid", "freeze_time")
def test_structured_trace_context(structured_logs_capture: JsonLogs):
    # A locally-created SDK span is enough: the formatter reads the span from
    # the active context, independent of the globally-registered provider.
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("test-span") as span:
        logger.info("with trace")
    span_context = span.get_span_context()

    parsed = structured_logs_capture.parse()[0]
    assert parsed["logging.googleapis.com/trace"] == format(
        span_context.trace_id, "032x"
    )
    assert parsed["logging.googleapis.com/spanId"] == format(
        span_context.span_id, "016x"
    )
    assert parsed["logging.googleapis.com/trace_sampled"] is True


@pytest.mark.usefixtures("freeze_uuid", "freeze_time")
def test_structured_trace_context_with_project(
    structured_logs_capture: JsonLogs, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("test-span") as span:
        logger.info("with trace")
    trace_id = format(span.get_span_context().trace_id, "032x")

    parsed = structured_logs_capture.parse()[0]
    assert parsed["logging.googleapis.com/trace"] == (
        f"projects/my-project/traces/{trace_id}"
    )


def test_structured_no_trace_context(structured_logs_capture: JsonLogs):
    # No active span -> no trace fields are added.
    logger.info("no trace")
    parsed = structured_logs_capture.parse()[0]
    assert "logging.googleapis.com/trace" not in parsed
    assert "logging.googleapis.com/spanId" not in parsed


@pytest.mark.usefixtures("freeze_uuid", "freeze_time")
def test_structured_info_http(structured_logs_capture: JsonLogs):
    logger.info(
        "test http request",
        extra={
            "httpRequest": {
                "method": "GET",
                "path": "/test",
                "latency": "0.123s",
            }
        },
    )

    assert structured_logs_capture.parse() == [
        {
            "severity": "INFO",
            "message": "test http request",
            "time": "2023-07-11T13:58:26.744488Z",
            "httpRequest": {"method": "GET", "path": "/test", "latency": "0.123s"},
            "logger": "test_logger",
        }
    ]
