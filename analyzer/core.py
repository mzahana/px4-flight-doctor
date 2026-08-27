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

    def mode_spans(self):
        """[(t0, t1, mode_name)] contiguous flight-mode runs over the whole log."""
        vs = self.get("vehicle_status")
        if vs is None or "nav_state" not in vs:
            return []
        t, ns = self.t(vs), vs["nav_state"]
        if len(ns) == 0:
            return []
        t_end = max(float(t[-1]), float(self.ulog.last_timestamp) / 1e6)
        spans, start, cur = [], float(t[0]), int(ns[0])
        for i in range(1, len(ns)):
            s = int(ns[i])
            if s != cur:
                spans.append((start, float(t[i]), nav_state_name(cur)))
                start, cur = float(t[i]), s
        spans.append((start, t_end, nav_state_name(cur)))
        return [s for s in spans if s[1] > s[0]]

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


# PX4 vehicle_status.nav_state -> short mode name. Slots that were reused across
# firmware versions carry the modern meaning; unknown values fall back to NAV_<n>.
NAV_STATES = {
    0: "MANUAL", 1: "ALTCTL", 2: "POSCTL", 3: "AUTO_MISSION", 4: "AUTO_LOITER",
    5: "AUTO_RTL", 6: "POSITION_SLOW", 10: "ACRO", 12: "DESCEND",
    13: "TERMINATION", 14: "OFFBOARD", 15: "STABILIZED", 17: "AUTO_TAKEOFF",
    18: "AUTO_LAND", 19: "FOLLOW_TARGET", 20: "PRECLAND", 21: "ORBIT",
    22: "AUTO_VTOL_TAKEOFF",
}


def nav_state_name(v):
    return NAV_STATES.get(int(v), f"NAV_{int(v)}")
