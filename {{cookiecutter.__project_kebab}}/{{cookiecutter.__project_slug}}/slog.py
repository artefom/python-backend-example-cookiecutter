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
from datetime import datetime, timezone
from typing import Any, Dict, Optional

__all__ = ["GcpStructuredFormatter", "logging_context"]

# Logging context labels to be used in async environment
CONTEXT_LABELS = contextvars.ContextVar[Optional[Dict[str, Any]]](
    "_logging_structured_labels_",
    default=None,
)


@contextmanager
def logging_context(**kwargs: Any | None):
    ctx = CONTEXT_LABELS.get()

    if ctx is None:
        ctx = kwargs.copy()
    else:
        ctx = {**ctx, **kwargs}

    token = CONTEXT_LABELS.set(ctx)
    try:
        yield
    finally:
        CONTEXT_LABELS.reset(token)


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
    "httpRequest",
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
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )


class GcpStructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            # Since we are formating with 'Z' at the end (a.k.a UTC time)
            # we must use our own converter oppsed to self.converter
            # to prevent invalid time formats if user configures self.converter
            "time": _local_timestamp_to_utc(record.created),
            "logging.googleapis.com/labels": self._format_labels(record),
        }

        if http_request := getattr(record, "httpRequest", None):
            payload["httpRequest"] = http_request

        if exc_info := record.exc_info:
            payload["traceback"] = "".join(traceback.format_exception(*exc_info))

        return json.dumps(payload)

    def _format_labels(self, record: logging.LogRecord) -> dict[str, Any]:
        if ctx_labels := CONTEXT_LABELS.get():
            labels = ctx_labels.copy()
        else:
            labels = dict()

        labels["logger"] = record.name

        for key, value in record.__dict__.items():
            if value is not None and key not in RESERVED:
                labels[key] = value

        return labels
