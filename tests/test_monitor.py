from types import SimpleNamespace

from crawlfb.monitor import ResourceMonitor


class FakeProc:
    """Stand-in for psutil.Process: returns a scripted cpu% and rss bytes."""

    def __init__(self, cpu: float = 0.0, rss: int = 0):
        self._cpu = cpu
        self.rss = rss
        self.cpu_calls = 0

    def cpu_percent(self, *args, **kwargs):
        self.cpu_calls += 1
        return self._cpu

    def memory_info(self):
        return SimpleNamespace(rss=self.rss)


def test_sample_converts_rss_to_mb_and_passes_cpu():
    mon = ResourceMonitor(procs=[FakeProc(cpu=12.5, rss=3 * 1048576)])
    s = mon.sample()
    assert s["cpu_pct"] == 12.5
    assert s["rss_mb"] == 3.0


def test_sample_sums_across_process_tree():
    mon = ResourceMonitor(procs=[
        FakeProc(cpu=1.0, rss=1048576),
        FakeProc(cpu=2.0, rss=2 * 1048576),
    ])
    s = mon.sample()
    assert s["cpu_pct"] == 3.0
    assert s["rss_mb"] == 3.0


def test_sample_tracks_peak_rss():
    proc = FakeProc(rss=1048576)
    mon = ResourceMonitor(procs=[proc])
    mon.sample()  # peak = 1 MB
    proc.rss = 5 * 1048576
    s = mon.sample()  # peak = 5 MB
    assert s["rss_mb"] == 5.0
    assert s["peak_mb"] == 5.0


def test_constructor_primes_cpu_baseline():
    proc = FakeProc()
    ResourceMonitor(procs=[proc])
    # psutil cpu_percent() needs a baseline call; ensure we prime it.
    assert proc.cpu_calls == 1


def test_line_formats_cpu_ram_peak():
    mon = ResourceMonitor(procs=[FakeProc(cpu=1.0, rss=1048576)])
    line = mon.line()
    assert "cpu=1.0%" in line
    assert "ram=1MB" in line
    assert "peak=1MB" in line
