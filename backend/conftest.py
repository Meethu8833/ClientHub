"""Project-wide pytest fixtures."""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """
    DRF throttling counts requests in the cache; without clearing it between
    tests, the login rate limit (10/min) would trip across the suite.
    """
    cache.clear()
    yield
