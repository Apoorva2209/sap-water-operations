"""Post-irrigation verification and fault classification.

Two questions after every run:
  1. Did the planned water actually flow?          (flow meter vs plan)
  2. Did the root zone respond as the model predicted? (2-depth soil moisture)
The combination of flow, pressure and soil response points to a likely fault.
These are rule-based hypotheses for a technician, not diagnoses.
"""
from __future__ import annotations

from .models import Fault, Measurement, Recommendation, Verification, Zone

DELIVERY_TOL = 0.2         # +/-20% of planned volume counts as delivered
MIN_RISE_FRACTION = 0.3    # soil must show at least 30% of predicted rise


def predicted_rise(zone: Zone, volume_l: float) -> float:
    """Expected average VWC rise over the root zone from a delivered volume."""
    mm = volume_l / zone.area_m2
    return mm / zone.crop.root_depth_mm


def verify(zone: Zone, rec: Recommendation, m: Measurement, nominal_pressure: float) -> Verification:
    planned = rec.volume_l
    ratio = m.delivered_l / planned if planned else 1.0
    flow_ratio = m.mean_flow_lpm / zone.valve_flow_lpm if zone.valve_flow_lpm else 1.0
    p_ratio = m.mean_pressure_kpa / nominal_pressure if nominal_pressure else 1.0

    # hydraulic faults first
    if m.pump_current_a < 1.0 and m.delivered_l < 0.2 * planned:
        return Verification(zone.zone_id, False, None, Fault.DRY_RUN, "pump ran with almost no current/flow: dry source or lost prime")
    if flow_ratio > 1.3 and p_ratio < 0.7:
        return Verification(zone.zone_id, False, None, Fault.LEAK, f"flow {flow_ratio:.0%} of nominal with low pressure: likely leak or burst")
    if flow_ratio < 0.6 and p_ratio > 1.15:
        return Verification(zone.zone_id, False, None, Fault.BLOCKAGE, f"flow {flow_ratio:.0%} of nominal with high pressure: likely blocked line or emitters")
    if m.delivered_l < 0.1 * planned and p_ratio > 1.0:
        return Verification(zone.zone_id, False, None, Fault.STUCK_VALVE, "pressure present but no flow: valve likely stuck closed")

    delivered_ok = abs(ratio - 1) <= DELIVERY_TOL

    # soil response
    vals = [m.vwc_shallow_before, m.vwc_shallow_after, m.vwc_deep_before, m.vwc_deep_after]
    if any(v is None for v in vals[:2]) and any(v is None for v in vals[2:]):
        return Verification(zone.zone_id, delivered_ok, None, Fault.SENSOR_FAULT, "no usable soil readings; cannot verify root-zone response")
    exp = predicted_rise(zone, m.delivered_l)
    rises = []
    if m.vwc_shallow_before is not None and m.vwc_shallow_after is not None:
        rises.append(m.vwc_shallow_after - m.vwc_shallow_before)
    if m.vwc_deep_before is not None and m.vwc_deep_after is not None:
        rises.append(m.vwc_deep_after - m.vwc_deep_before)
    obs = max(rises)
    if delivered_ok and obs < MIN_RISE_FRACTION * exp:
        if len(rises) == 2 and rises[0] < 0.005 and rises[1] < 0.005:
            return Verification(zone.zone_id, True, False, Fault.INEFFECTIVE,
                                f"water delivered but soil did not respond (expected +{exp:.3f} VWC): emitter placement, runoff or wrong zone wiring")
        return Verification(zone.zone_id, True, False, Fault.SENSOR_FAULT,
                            f"one depth did not respond (observed +{obs:.3f}, expected +{exp:.3f}): check sensor contact")
    if not delivered_ok:
        return Verification(zone.zone_id, False, obs >= MIN_RISE_FRACTION * exp, Fault.NONE,
                            f"delivered {m.delivered_l:.0f} L vs planned {planned:.0f} L ({ratio:.0%})")
    return Verification(zone.zone_id, True, True, Fault.NONE,
                        f"delivered {m.delivered_l:.0f} L ({ratio:.0%} of plan); soil +{obs:.3f} VWC vs expected +{exp:.3f}")
