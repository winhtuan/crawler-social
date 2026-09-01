from crawlfb.paginate import update_stall
from crawlfb.intercept import FeedInterceptor


def test_update_stall_resets_on_growth():
    stall, stop = update_stall(count=5, last_count=4, stall=3, stall_limit=5)
    assert stall == 0
    assert stop is False


def test_update_stall_increments_on_no_growth():
    stall, stop = update_stall(count=4, last_count=4, stall=0, stall_limit=5)
    assert stall == 1
    assert stop is False


def test_update_stall_stops_at_limit():
    stall, stop = update_stall(count=4, last_count=4, stall=4, stall_limit=5)
    assert stall == 5
    assert stop is True


class _FakePage:
    """Records page listeners so attach()/detach() are asserted without a browser."""

    def __init__(self):
        self.listeners: list[tuple[str, object]] = []

    def on(self, event: str, handler) -> None:
        self.listeners.append((event, handler))

    def remove_listener(self, event: str, handler) -> None:
        self.listeners.remove((event, handler))


def test_feed_interceptor_attach_adds_listener_detach_removes_it():
    page = _FakePage()
    inter = FeedInterceptor(page)
    inter.attach()
    assert page.listeners == [("response", inter._on_response)]
    inter.detach()
    assert page.listeners == []


def test_feed_interceptor_detach_before_attach_is_noop():
    # detach() swallows remove_listener failures, so calling it on an unattached
    # interceptor must not raise (mirrors CommentInterceptor.detach()).
    page = _FakePage()
    inter = FeedInterceptor(page)
    inter.detach()
    assert page.listeners == []
