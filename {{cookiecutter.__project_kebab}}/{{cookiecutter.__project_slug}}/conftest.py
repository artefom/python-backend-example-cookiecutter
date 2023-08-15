"""
common fixtures and classes for tests
"""
import io
import json
import logging
from typing import Any, Dict, Generator, List

import pytest

from .slog import GcpStructuredFormatter


class JsonLogs(io.StringIO):
    def parse(self) -> List[Dict[str, Any]]:
        lines = list()
        for line in self.getvalue().splitlines():
            if not line:
                continue
            lines.append(json.loads(line))
        return lines


@pytest.fixture()
def structured_logs_capture() -> Generator[JsonLogs, None, None]:
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
