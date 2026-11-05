"""API-key pool. Keys come from the environment only and are never logged or returned.

Discovers ``<PREFIX>``, ``<PREFIX>_1``, ``<PREFIX>_2`` ... so adding a 4th NVIDIA key
is just exporting ``NVIDIA_API_KEY_4``. Identical values are de-duplicated.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field


@dataclass
class _Slot:
    name: str                     # env var name only; safe to log
    value: str = field(repr=False)
    cooldown_until: float = 0.0
    failures: int = 0


class KeyPool:
    def __init__(self, slots: list[_Slot], clock=time.monotonic):
        if not slots:
            raise RuntimeError("no API keys found in environment")
        self._slots = slots
        self._i = 0
        self._lock = threading.Lock()
        self._clock = clock

    @classmethod
    def from_env(cls, prefix: str, env=None, clock=time.monotonic) -> KeyPool:
        env = os.environ if env is None else env
        pat = re.compile(rf"^{re.escape(prefix)}(_\d+)?$")
        names = sorted((n for n in env if pat.match(n)), key=lambda n: (len(n), n))
        seen, slots = set(), []
        for n in names:
            v = (env.get(n) or "").strip()
            if v and v not in seen:
                seen.add(v)
                slots.append(_Slot(n, v))
        return cls(slots, clock)

    def __len__(self) -> int:
        return len(self._slots)

    @property
    def names(self) -> list[str]:
        return [s.name for s in self._slots]

    def acquire(self) -> _Slot:
        """Round-robin over keys that are not cooling down; if all cool, take the soonest."""
        with self._lock:
            now = self._clock()
            for _ in range(len(self._slots)):
                s = self._slots[self._i % len(self._slots)]
                self._i += 1
                if s.cooldown_until <= now:
                    return s
            return min(self._slots, key=lambda s: s.cooldown_until)

    def report(self, slot: _Slot, ok: bool, retry_after: float = 30.0) -> None:
        with self._lock:
            if ok:
                slot.failures = 0
                slot.cooldown_until = 0.0
            else:
                slot.failures += 1
                slot.cooldown_until = self._clock() + min(retry_after * slot.failures, 300.0)
