"""
tests for structured logging module (slog.py)
"""

import asyncio
import io
import json
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Generator, List
from unittest.mock import ANY

import pytest

from .slog import GcpStructuredFormatter, logging_context

logger = logging.getLogger("test_logger")


class JsonLogs(io.StringIO):
    def parse(self) -> List[Dict[str, Any]]:
        lines = list()
        for line in self.getvalue().splitlines():
            if not line:
                continue
            lines.append(json.loads(line))
        return lines


@contextmanager
def _caputre_logs() -> Generator[JsonLogs, None, None]:
    output = JsonLogs()

    root_logger = logging.getLogger()

    # Copy existing loggers and clear the array
    # (do not just re-assign so references to old handlers list remain valid)
    handlers = root_logger.handlers.copy()
    root_logger.handlers.clear()

    # Add stream logger that writes to our output
    handler = logging.StreamHandler(output)

    handler.formatter = GcpStructuredFormatter()

    root_logger.handlers.append(handler)

    try:
        yield output
    finally:
        # Return loggers back
        root_logger.handlers.clear()
        root_logger.handlers.extend(handlers)


@pytest.fixture()
def freeze_time(monkeypatch: pytest.MonkeyPatch):
    def mock_time() -> float:
        return 1689083906.744488

    monkeypatch.setattr(time, "time", mock_time)


@pytest.fixture()
def freeze_uuid(monkeypatch: pytest.MonkeyPatch):
    def mock_uuid4() -> uuid.UUID:
        return uuid.UUID("a4f3fc0f-3caf-4bc7-8a71-e19069248dc2")

    monkeypatch.setattr(uuid, "uuid4", mock_uuid4)


@pytest.fixture()
def mock_gmtime(monkeypatch: pytest.MonkeyPatch):
    """
    Mock gmtime to return local time
    so the tests are invariant to local machine timezone
    """

    monkeypatch.setattr(time, "gmtime", time.localtime)


@pytest.mark.asyncio
@pytest.mark.usefixtures("freeze_uuid", "freeze_time", "mock_gmtime")
async def test_structured_logging():
    # Monkey-patch existing logging handlers

    with _caputre_logs() as logs:
        logger.info("test info")
        logger.warning("test warning")
        logger.info("test extra", extra={"foo": "bar"})
        logger.info("test args: %s: %s", "foo", "bar")

        with logging_context(some_var="some_val"):
            logger.info("test context")
            logger.info("test some context again")

            with logging_context(nested="nested_val"):
                logger.info("test nested")

        logger.info("test context reset")

        try:
            raise ValueError()
        except ValueError:
            logger.exception("test exception")

        async def task1():
            with logging_context(task_name="task1"):
                logger.info("Hello from task 1")

        async def task2():
            with logging_context(task_name="task2"):
                logger.info("Hello from task 2")

        # Test async tasks
        with logging_context(parent="foo"):
            await asyncio.gather(task1(), task2())

    assert logs.parse() == [
        {
            "severity": "INFO",
            "message": "test info",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {"logger": "test_logger"},
        },
        {
            "severity": "WARNING",
            "message": "test warning",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {"logger": "test_logger"},
        },
        {
            "severity": "INFO",
            "message": "test extra",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {
                "logger": "test_logger",
                "foo": "bar",
            },
        },
        {
            "severity": "INFO",
            "message": "test args: foo: bar",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {"logger": "test_logger"},
        },
        {
            "severity": "INFO",
            "message": "test context",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {
                "some_var": "some_val",
                "logger": "test_logger",
            },
        },
        {
            "severity": "INFO",
            "message": "test some context again",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {
                "some_var": "some_val",
                "logger": "test_logger",
            },
        },
        {
            "severity": "INFO",
            "message": "test nested",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {
                "some_var": "some_val",
                "nested": "nested_val",
                "logger": "test_logger",
            },
        },
        {
            "severity": "INFO",
            "message": "test context reset",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {"logger": "test_logger"},
        },
        {
            "severity": "ERROR",
            "message": "test exception",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {"logger": "test_logger"},
            "traceback": ANY,
        },
        {
            "severity": "INFO",
            "message": "Hello from task 1",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {
                "task_name": "task1",
                "logger": "test_logger",
                "parent": "foo",
            },
        },
        {
            "severity": "INFO",
            "message": "Hello from task 2",
            "time": "2023-07-11T13:58:26.744488Z",
            "logging.googleapis.com/labels": {
                "task_name": "task2",
                "logger": "test_logger",
                "parent": "foo",
            },
        },
    ]
