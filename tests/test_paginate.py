from crawlfb.paginate import update_stall


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
