import random
from crawlfb.humanizer import Humanizer

def test_delay_is_never_negative():
    h = Humanizer(base=3.0, jitter=2.0, rng=random.Random(1))
    for _ in range(100):
        assert h.next_delay() >= 1.0

def test_delay_stays_within_base_plus_minus_jitter():
    h = Humanizer(base=3.0, jitter=1.0, rng=random.Random(2))
    delays = [h.next_delay() for _ in range(100)]
    assert max(delays) <= 4.0
    assert min(delays) >= 2.0

def test_scroll_steps_are_positive_and_smaller_than_distance():
    h = Humanizer(base=1.0, jitter=0.5, rng=random.Random(3))
    steps = h.scroll_steps(distance=2000)
    assert all(0 < s <= 600 for s in steps)
    assert sum(steps) >= 2000
