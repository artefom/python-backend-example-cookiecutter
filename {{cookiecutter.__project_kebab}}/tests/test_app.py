"""
Example unit tests file
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_index(client: AsyncClient) -> None:
    response = await client.get("/docs")
    assert response.status_code == 200
