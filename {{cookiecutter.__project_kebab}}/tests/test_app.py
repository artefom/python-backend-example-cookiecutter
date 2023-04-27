"""
Example unit tests file
"""
import os

from fastapi.testclient import TestClient

from {{cookiecutter.__project_slug}}.main import make_app

os.environ["TEST_ENV_VAR"] = "123"


client = TestClient(make_app())


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_index() -> None:
    response = client.get("/")
    assert response.status_code == 200
