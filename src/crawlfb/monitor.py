"""Process-tree CPU + RAM sampling for crawl logging.

Measures the crawler *and* its browser (Chromium) children — the browser
dominates resource use, so sampling only the python process would under-report
by orders of magnitude. `procs` is injectable for tests; when None the live
process tree is re-enumerated on every sample (children appear once the browser
launches).

cpu_percent() reports the delta since the *previous* call on the same Process
object, so a freshly constructed Process always reads 0.0. The live tree is
therefore cached by pid and reused across samples; new children are primed on
first appearance.
"""
from __future__ import annotations

import psutil


class ResourceMonitor:
    def __init__(self, procs: "list | None" = None) -> None:
        self._fixed = procs
        self._cache: dict[int, object] = {}
        self._peak_rss = 0
        for p in self._current():
            self._prime(p)

    @staticmethod
    def _prime(p) -> None:
        try:
            p.cpu_percent()
        except Exception:
            pass

    def _current(self) -> list:
        if self._fixed is not None:
            return self._fixed
        try:
            root = psutil.Process()
            procs = [root] + root.children(recursive=True)
        except Exception:
            procs = []
        out = []
        live = set()
        for p in procs:
            live.add(p.pid)
            cached = self._cache.get(p.pid)
            if cached is None:
                self._cache[p.pid] = p
                self._prime(p)  # establish the cpu_percent baseline
                cached = p
            out.append(cached)
        for pid in [pid for pid in self._cache if pid not in live]:
            del self._cache[pid]
        return out

    def sample(self) -> dict:
        """Aggregate cpu% and resident memory across the process tree, in MB."""
        cpu = 0.0
        rss = 0
        for p in self._current():
            try:
                cpu += p.cpu_percent()
                rss += p.memory_info().rss
            except Exception:
                continue
        self._peak_rss = max(self._peak_rss, rss)
        return {
            "cpu_pct": cpu,
            "rss_mb": rss / 1048576.0,
            "peak_mb": self._peak_rss / 1048576.0,
        }

    def line(self) -> str:
        """One-line human-readable snapshot for the log."""
        s = self.sample()
        return f"cpu={s['cpu_pct']:.1f}% ram={s['rss_mb']:.0f}MB peak={s['peak_mb']:.0f}MB"
