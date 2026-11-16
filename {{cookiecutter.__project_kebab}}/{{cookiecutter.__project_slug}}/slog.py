"""
Implementation of structured logging handler for google cloud logs

more details here
https://cloud.google.com/logging/docs/structured-logging


Usage:

use GcpStructuredFormatter as formatter when configuring logger,
use logging_context or extra=... to add context to logs

see 'slog_tests.test_structured_logging' for more detailed usage example
"""

import contextvars
import json
import logging
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

__all__ = ["GcpStructuredFormatter", "logging_context"]

# Logging context to be used in async environment
LOGGING_CONTEXT = contextvars.ContextVar[dict[str, Any] | None](
    "_logging_structured_context_",
    default=None,
)


@contextmanager
def logging_context(**kwargs: Any | None):
    ctx = LOGGING_CONTEXT.get()

    if ctx is None:
        ctx = kwargs.copy()
    else:
        ctx = {**ctx, **kwargs}

    token = LOGGING_CONTEXT.set(ctx)
    try:
        yield
    finally:
        LOGGING_CONTEXT.reset(token)


# Set of reserved by logging package keywords that are not logged by default
# We can use this in code to automatically add anything into logs that
# is passed in extra={..}
RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}


def _local_timestamp_to_utc(local_unix_timestamp: float) -> str:
    """
    Format local unix timestamp to string accepted by google cloud
    """
    # This is horrible, but we cannot rely on time.gmtime to convert
    # local time to utc because it drops sub-second part of the timestamp
    # so we need to use datetime and .astimezone() to convert to datetime
    # in local timezone and then convert it to utc preserving the sub-second part
    # also, record.msecs does not store anything less than millisecond
    # so we will be loosing resolution
    # remember - record.created is created using time.time()

    return (
        datetime.fromtimestamp(local_unix_timestamp)
        .astimezone()
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )


def _add_trace_context(payload: dict[str, Any], project_id: str | None) -> None:
    """
    Stamp the active OpenTelemetry span onto the log entry using the special
    fields Google Cloud Logging recognises, so all log lines of a single request
    can be grouped by trace.

    https://cloud.google.com/logging/docs/structured-logging#special-payload-fields

    Does nothing when no valid span is active (e.g. startup or non-HTTP logs).
    """
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return

    trace_id = format(span_context.trace_id, "032x")
    payload["logging.googleapis.com/trace"] = (
        f"projects/{project_id}/traces/{trace_id}" if project_id else trace_id
    )
    payload["logging.googleapis.com/spanId"] = format(span_context.span_id, "016x")
    payload["logging.googleapis.com/trace_sampled"] = span_context.trace_flags.sampled


class GcpStructuredFormatter(logging.Formatter):
    def __init__(self, project_id: str | None = None) -> None:
        super().__init__()
        self.project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            # Since we are formating with 'Z' at the end (a.k.a UTC time)
            # we must use our own converter oppsed to self.converter
            # to prevent invalid time formats if user configures self.converter
            "time": _local_timestamp_to_utc(record.created),
            "logger": record.name,
        }

        self._add_context(payload, record)
        _add_trace_context(payload, self.project_id)

        if exc_info := record.exc_info:
            payload["traceback"] = "".join(traceback.format_exception(*exc_info))

        return json.dumps(payload, default=str)

    def _add_context(self, payload: dict[str, Any], record: logging.LogRecord) -> None:
        if ctx := LOGGING_CONTEXT.get():
            for key, value in ctx.items():
                if value is not None:
                    payload[key] = value

        for key, value in record.__dict__.items():
            if value is not None and key not in RESERVED:
                payload[key] = value
