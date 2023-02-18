"""
Sample hello module
"""

import os


def say_hello(name: str) -> str:
    if name == "error":
        raise ValueError("Some error occurred")
    return f"{os.environ['TEST_ENV_VAR']} {name}"
