"""Process-wide admission for serialized continuity work, not an RSS claim."""

import threading
import sys


class WorksetBudget:
    def __init__(self, limit=32*1024*1024):
        self.limit = limit
        self._lock = threading.Lock()
        self._leases = {}

    def acquire(self, key, size):
        if type(size) is not int or size < 0:
            raise ValueError("workset_size_invalid")
        with self._lock:
            if sum(self._leases.values()) - self._leases.get(key, 0) + size > self.limit:
                return False
            self._leases[key] = size
            return True

    def release(self, key):
        with self._lock:
            self._leases.pop(key, None)


# PluginManager imports each profile under a separate package and purges it on
# reload. Admission must outlive that package, or each profile gets 32 MiB.
ACTIVE_WORKSETS = WorksetBudget()
COLD_PLANS = WorksetBudget(8*1024*1024)
PREPARATION_WORKSETS = WorksetBudget(8*1024*1024)
PREPARATION_LOCK = threading.Lock()
_process = sys.modules.setdefault("_hermes_continuity_process_budget_v1", sys.modules[__name__])
ACTIVE_WORKSETS = _process.ACTIVE_WORKSETS
COLD_PLANS = _process.COLD_PLANS
PREPARATION_WORKSETS = _process.PREPARATION_WORKSETS
PREPARATION_LOCK = _process.PREPARATION_LOCK
