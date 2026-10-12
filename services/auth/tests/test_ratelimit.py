from app.ratelimit import LoginThrottle


def test_blocks_after_max_failures_and_expires():
    t = LoginThrottle(max_failures=3, window_seconds=60)
    for i in range(3):
        assert not t.is_blocked("a", now=100 + i)
        t.record_failure("a", now=100 + i)
    assert t.is_blocked("a", now=103)
    assert not t.is_blocked("b", now=103)
    assert not t.is_blocked("a", now=200)  # window passed


def test_reset_clears():
    t = LoginThrottle(max_failures=1)
    t.record_failure("a")
    assert t.is_blocked("a")
    t.reset("a")
    assert not t.is_blocked("a")
