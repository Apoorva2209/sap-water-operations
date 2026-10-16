"""Core data entities for SAP.

All volumes are litres, depths are millimetres of water, times are minutes,
soil moisture is volumetric water content (VWC, fraction 0-1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Mode(str, Enum):
    AUTO = "auto"                  # execute within safety limits
    NEEDS_APPROVAL = "needs_approval"
    INSPECT = "inspect"            # likely fault, send a person
    CONSERVATIVE = "conservative"  # data too poor: small fixed safety run
    HOLD = "hold"                  # no irrigation needed / not allowed


class Fault(str, Enum):
    NONE = "none"
    LEAK = "leak"
    BLOCKAGE = "blockage"
    DRY_RUN = "dry_run"
    STUCK_VALVE = "stuck_valve"
    SENSOR_FAULT = "sensor_fault"
    INEFFECTIVE = "ineffective_irrigation"


@dataclass
class Crop:
    name: str
    kc: float                  # FAO-56 crop coefficient for the current stage
    root_depth_mm: float       # effective root depth
    mad: float = 0.5           # management allowed depletion (fraction of TAW)
    priority: float = 1.0      # agreed risk weight (higher = protect first)


@dataclass
class Soil:
    name: str
    field_capacity: float      # VWC
    wilting_point: float       # VWC

    def taw_mm(self, root_depth_mm: float) -> float:
        """Total available water in the root zone (mm)."""
        return (self.field_capacity - self.wilting_point) * root_depth_mm


@dataclass
class Zone:
    zone_id: str
    member: str                # farmer who owns the plot
    area_m2: float
    crop: Crop
    soil: Soil
    valve_flow_lpm: float      # nominal flow when the valve is open
    min_run_min: float = 3.0
    max_run_min: float = 120.0


@dataclass
class Source:
    """Shared water source (tank / borewell) and pump."""
    available_l: float
    min_reserve_l: float       # never draw below this
    pump_max_lpm: float
    nominal_pressure_kpa: float
    energy_kwh_per_1000l: float
    energy_budget_kwh: float   # e.g. today's solar estimate


@dataclass
class SensorReading:
    zone_id: str
    vwc_shallow: Optional[float]   # ~10 cm
    vwc_deep: Optional[float]      # ~30 cm
    age_min: float = 0.0           # minutes since the reading


@dataclass
class Weather:
    et0_mm: float              # reference evapotranspiration for the day
    rain_forecast_mm: float
    age_h: float               # hours since forecast was issued


@dataclass
class Estimate:
    zone_id: str
    need_mm: float
    need_l: float
    confidence: float          # 0-1
    risk: float                # crop risk if delayed, 0-1
    reasons: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    zone_id: str
    mode: Mode
    volume_l: float
    duration_min: float
    energy_kwh: float
    confidence: float
    risk: float
    reasons: list[str]
    constraints: list[str]


@dataclass
class Measurement:
    """What actually happened during a run (from flow / pressure / current sensors)."""
    zone_id: str
    delivered_l: float
    mean_flow_lpm: float
    mean_pressure_kpa: float
    pump_current_a: float
    vwc_shallow_before: Optional[float]
    vwc_shallow_after: Optional[float]
    vwc_deep_before: Optional[float]
    vwc_deep_after: Optional[float]


@dataclass
class Verification:
    zone_id: str
    delivered_ok: bool
    soil_response_ok: Optional[bool]
    fault: Fault
    detail: str
