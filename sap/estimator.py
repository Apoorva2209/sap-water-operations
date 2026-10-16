"""Interpretable water-need estimation with an explicit confidence score.

Baseline method (no ML): FAO-56 style root-zone water balance.
    depletion = TAW * (1 - relative soil water from sensors)
    need     = depletion - readily available water + tomorrow's crop use - effective rain
Confidence is reduced, with a stated reason, for every data-quality problem.
"""
from __future__ import annotations

from .models import Crop, Estimate, SensorReading, Soil, Weather, Zone

STALE_SENSOR_MIN = 60.0
STALE_FORECAST_H = 12.0
DISAGREE_VWC = 0.12      # shallow vs deep difference that is physically suspicious
RAIN_EFFECTIVE = 0.8     # fraction of forecast rain assumed to reach the root zone
TRIGGER = 0.5        # irrigate when projected depletion passes 50% of readily available water


def _plausible(v):
    return v is not None and 0.02 <= v <= 0.60


def root_zone_vwc(r: SensorReading, soil: Soil) -> tuple[float | None, float, list[str]]:
    """Combine two depths into one root-zone VWC. Returns (vwc, confidence, reasons)."""
    reasons, conf = [], 1.0
    s_ok, d_ok = _plausible(r.vwc_shallow), _plausible(r.vwc_deep)
    if not s_ok and not d_ok:
        return None, 0.0, ["both soil sensors missing or implausible"]
    if s_ok and d_ok:
        vwc = 0.4 * r.vwc_shallow + 0.6 * r.vwc_deep
        if abs(r.vwc_shallow - r.vwc_deep) > DISAGREE_VWC:
            conf -= 0.35
            reasons.append(f"sensors disagree (10 cm {r.vwc_shallow:.2f} vs 30 cm {r.vwc_deep:.2f})")
    else:
        vwc = r.vwc_shallow if s_ok else r.vwc_deep
        conf -= 0.3
        reasons.append(("deep" if s_ok else "shallow") + " sensor missing; using one depth")
    if r.age_min > STALE_SENSOR_MIN:
        conf -= 0.25
        reasons.append(f"soil reading is {r.age_min:.0f} min old")
    vwc = min(max(vwc, soil.wilting_point), soil.field_capacity * 1.1)
    return vwc, max(conf, 0.0), reasons


def estimate(zone: Zone, reading: SensorReading, weather: Weather) -> Estimate:
    crop: Crop = zone.crop
    soil: Soil = zone.soil
    taw = soil.taw_mm(crop.root_depth_mm)
    raw = crop.mad * taw                                  # readily available water
    vwc, conf, reasons = root_zone_vwc(reading, soil)

    if weather.age_h > STALE_FORECAST_H:
        conf -= 0.2
        reasons.append(f"weather forecast is {weather.age_h:.0f} h old; rain ignored")
        rain = 0.0
    else:
        rain = RAIN_EFFECTIVE * weather.rain_forecast_mm

    etc = crop.kc * weather.et0_mm                        # crop water use for the next day
    if vwc is None:
        depletion = raw                                   # assume at the trigger point
    else:
        depletion = max(0.0, (soil.field_capacity - vwc) * crop.root_depth_mm)

    # refill to field capacity only if the zone will cross the allowed depletion by tomorrow
    projected = depletion + etc - rain
    need_mm = max(0.0, projected) if projected > raw * TRIGGER else 0.0
    need_mm = min(need_mm, taw)
    risk = min(1.0, max(0.0, projected / taw)) * crop.priority
    risk = min(risk, 1.0)

    if need_mm == 0.0:
        reasons.append(f"root zone above trigger (depletion {depletion:.1f} mm, ETc {etc:.1f} mm, rain {rain:.1f} mm)")
    else:
        reasons.append(f"depletion {depletion:.1f} mm + ETc {etc:.1f} mm - rain {rain:.1f} mm exceeds trigger {raw*TRIGGER:.1f} mm")

    need_l = need_mm * zone.area_m2                       # 1 mm over 1 m2 = 1 L
    return Estimate(zone.zone_id, round(need_mm, 2), round(need_l, 1), round(max(conf, 0.0), 2),
                    round(risk, 2), reasons)
