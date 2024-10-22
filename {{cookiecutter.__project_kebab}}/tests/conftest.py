"""
Example unit tests file
"""

# The link to the testing practices
# https://fastapi.tiangolo.com/advanced/async-tests/#example


from typing import AsyncGenerator

import httpx
import pytest_asyncio

from {{cookiecutter.__project_slug}}.main import make_app


# The 'raw' client of our application.
#
# During tests we skip the whole main() ... function
# and create the app directly.
#
# Usually we would connect to any databases, initialize 'ClientSession' to
# access external services, etc.. in the main function.
#
# Since the main will not be called, we need to mock these connections
# in this client explicitly
#
# Making the client could be a pretty expensive operation, so we specify here scope
# to be module.
@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    # Feel free to connect here to database, or create any global contest
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(make_app("")), base_url="http://test"
    ) as aclient:
        yield aclient
