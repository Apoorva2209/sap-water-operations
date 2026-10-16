"""Safety interlocks applied by the edge controller during every run.

These run locally and do not depend on the network. Any trip closes the valve
and stops the pump, then logs the event and alerts the operator.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SafetyLimits:
    min_tank_l: float = 100.0          # dry-run guard on the source
    min_pump_current_a: float = 1.0    # below this with pump ON = dry-run / lost prime
    max_pump_current_a: float = 12.0   # overload / locked rotor
    low_flow_ratio: float = 0.5        # < 50% of nominal flow = blockage or dry-run
    high_flow_ratio: float = 1.5       # > 150% of nominal flow = burst / leak
    low_pressure_ratio: float = 0.5    # pressure collapse = burst pipe
    grace_s: float = 20.0              # ignore transients right after start


@dataclass
class Tick:
    t_s: float
    tank_l: float
    flow_lpm: float
    pressure_kpa: float
    pump_current_a: float
    estop: bool = False
    manual_off: bool = False


def check(tick: Tick, nominal_flow: float, nominal_pressure: float, lim: SafetyLimits = SafetyLimits()) -> str | None:
    """Return a trip reason, or None if it is safe to keep running."""
    if tick.estop:
        return "emergency stop pressed"
    if tick.manual_off:
        return "manual override: operator stopped the run"
    if tick.tank_l <= lim.min_tank_l:
        return f"source below reserve ({tick.tank_l:.0f} L)"
    if tick.pump_current_a > lim.max_pump_current_a:
        return f"pump overcurrent {tick.pump_current_a:.1f} A"
    if tick.t_s < lim.grace_s:
        return None
    if tick.pump_current_a < lim.min_pump_current_a:
        return f"pump dry-run suspected (current {tick.pump_current_a:.1f} A)"
    if tick.flow_lpm < lim.low_flow_ratio * nominal_flow:
        return f"low flow {tick.flow_lpm:.1f} L/min (blockage, closed valve or dry-run)"
    if tick.flow_lpm > lim.high_flow_ratio * nominal_flow:
        return f"high flow {tick.flow_lpm:.1f} L/min (possible burst or leak)"
    if tick.pressure_kpa < lim.low_pressure_ratio * nominal_pressure:
        return f"pressure collapse {tick.pressure_kpa:.0f} kPa (possible burst)"
    return None
