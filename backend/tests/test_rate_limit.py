import pytest

from backend.rate_limit import SlidingWindowRateLimiter


def test_allows_requests_until_limit_then_rejects():
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)

    assert limiter.allow("client") is True
    assert limiter.allow("client") is True
    assert limiter.allow("client") is False
    assert limiter.allow("other-client") is True


@pytest.mark.parametrize("limit,window", [(0, 1), (1, 0), (-1, 10)])
def test_rejects_invalid_configuration(limit, window):
    with pytest.raises(ValueError, match="must be positive"):
        SlidingWindowRateLimiter(limit, window)
