"""Core data structures and log loading helpers."""
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
from pyulog import ULog


class Severity(IntEnum):
    OK = 0
    INFO = 1
    WARNING = 2
    CRITICAL = 3

    @property
    def label(self):
        return self.name

    @property
    def emoji(self):
        return {0: "✅", 1: "ℹ️ ", 2: "⚠️ ", 3: "🛑"}[int(self)]


@dataclass
class Finding:
    severity: Severity
    category: str          # short group name, e.g. "Propulsion"
    title: str             # one-line statement
    detail: str = ""       # multi-line explanation with numbers
    fixes: list = field(default_factory=list)   # concrete actions / param commands
    doc: str = ""          # related doc file in docs/


class Log:
    """Thin convenience wrapper around a parsed ULog."""

    def __init__(self, path):
        self.path = path
        self.ulog = ULog(path)
        self.params = self.ulog.initial_parameters
        self._cache = {}

    def has(self, name, instance=0):
        return self.get(name, instance) is not None

    def get(self, name, instance=0):
        """Return the topic's data dict, or None if absent."""
        key = (name, instance)
        if key not in self._cache:
            try:
                self._cache[key] = self.ulog.get_dataset(name, instance).data
            except (KeyError, IndexError, ValueError):
                self._cache[key] = None
        return self._cache[key]

    def t(self, data):
        """Timestamps of a topic dict in seconds (float64)."""
        return data["timestamp"].astype(np.float64) / 1e6

    def param(self, name, default=None):
        return self.params.get(name, default)

    # ---- flight phases -------------------------------------------------
    def in_air_window(self):
        """(t_start, t_end) of the airborne period, or None."""
        ld = self.get("vehicle_land_detected")
        if ld is None:
            return None
        t = self.t(ld)
        air = ld["landed"] == 0
        if not air.any():
            return None
        return float(t[air][0]), float(t[air][-1])

    def hover_mask(self, topic_t):
        """Mask over `topic_t` (seconds) for quasi-static hover samples."""
        w = self.in_air_window()
        lp = self.get("vehicle_local_position")
        m = np.ones_like(topic_t, dtype=bool)
        if w:
            m &= (topic_t >= w[0] + 3.0) & (topic_t <= w[1] - 1.0)
        if lp is not None:
            tl = self.t(lp)
            vz = np.interp(topic_t, tl, lp["vz"])
            vxy = np.interp(topic_t, tl, np.hypot(lp["vx"], lp["vy"]))
            m &= (np.abs(vz) < 0.3) & (vxy < 1.0)
        return m


AUTOTUNE_STATES = {
    0: "IDLE", 1: "INIT", 2: "ROLL_AMP", 3: "ROLL", 4: "ROLL_PAUSE",
    5: "PITCH_AMP", 6: "PITCH", 7: "PITCH_PAUSE", 8: "YAW_AMP", 9: "YAW",
    10: "YAW_PAUSE", 11: "VERIFICATION", 12: "APPLY", 13: "TEST",
    14: "COMPLETE", 15: "FAIL", 16: "WAIT_FOR_DISARM",
}
