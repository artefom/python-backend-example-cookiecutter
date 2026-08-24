import io
import json
from typing import Any


class JsonLogs(io.StringIO):
    def parse(self) -> list[dict[str, Any]]:
        lines = []
        for line in self.getvalue().splitlines():
            if not line:
                continue
            lines.append(json.loads(line))
        return lines
