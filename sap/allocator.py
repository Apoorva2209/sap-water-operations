"""Allocate limited shared water across zones.

Interpretable greedy allocation (a baseline before any optimiser/ML):
  1. Zones are ranked by risk-if-delayed, weighted by agreed member priority.
  2. Each zone gets up to its estimated need while source, reserve, pump and
     energy limits allow, and run time stays inside min/max limits.
  3. The decision mode is chosen from confidence and conflicts:
       confidence >= AUTO_CONF and no conflict -> AUTO
       AUTO_CONF > confidence >= REVIEW_CONF   -> NEEDS_APPROVAL
       confidence < REVIEW_CONF                -> CONSERVATIVE (small safety run) or HOLD
  4. Zones with an open fault are never irrigated automatically -> INSPECT.
Every applied limit is recorded so the operator can see why.
"""
from __future__ import annotations

from .models import Estimate, Mode, Recommendation, Source, Zone

AUTO_CONF = 0.75
REVIEW_CONF = 0.45
CONSERVATIVE_FRACTION = 0.3     # fraction of need given when data is poor but risk is high


def plan(zones: list[Zone], estimates: dict[str, Estimate], source: Source,
         open_faults: set[str] | None = None, fair_share: bool = True) -> list[Recommendation]:
    open_faults = open_faults or set()
    usable = max(0.0, source.available_l - source.min_reserve_l)
    energy_left = source.energy_budget_kwh
    total_need = sum(e.need_l for e in estimates.values()) or 1.0
    recs: list[Recommendation] = []

    order = sorted(zones, key=lambda z: (estimates[z.zone_id].risk, estimates[z.zone_id].confidence), reverse=True)
    for z in order:
        e = estimates[z.zone_id]
        reasons, constraints = list(e.reasons), []

        if z.zone_id in open_faults:
            recs.append(Recommendation(z.zone_id, Mode.INSPECT, 0, 0, 0, e.confidence, e.risk,
                                       reasons + ["open fault on this zone; inspect before irrigating"], ["fault lockout"]))
            continue
        if e.need_l <= 0:
            recs.append(Recommendation(z.zone_id, Mode.HOLD, 0, 0, 0, e.confidence, e.risk, reasons, []))
            continue

        if e.confidence >= AUTO_CONF:
            mode, target = Mode.AUTO, e.need_l
        elif e.confidence >= REVIEW_CONF:
            mode, target = Mode.NEEDS_APPROVAL, e.need_l
        elif e.risk >= 0.6:
            mode, target = Mode.CONSERVATIVE, e.need_l * CONSERVATIVE_FRACTION
            reasons.append("data confidence too low; conservative safety run only")
        else:
            recs.append(Recommendation(z.zone_id, Mode.HOLD, 0, 0, 0, e.confidence, e.risk,
                                       reasons + ["data confidence too low and risk is low; wait for better data"], []))
            continue

        vol = target
        if usable < total_need and fair_share:
            share = usable * (e.need_l / total_need)
            if vol > share and e.risk < 0.8:
                vol = share
                constraints.append(f"limited source: proportional share {share:.0f} L")
        if vol > usable:
            vol = usable
            constraints.append(f"source limit: {usable:.0f} L left above reserve")
        flow = min(z.valve_flow_lpm, source.pump_max_lpm)
        dur = vol / flow if flow else 0
        if dur > z.max_run_min:
            dur = z.max_run_min; vol = dur * flow
            constraints.append(f"max run time {z.max_run_min:.0f} min")
        energy = vol / 1000 * source.energy_kwh_per_1000l
        if energy > energy_left:
            vol = energy_left / source.energy_kwh_per_1000l * 1000 if source.energy_kwh_per_1000l else vol
            dur = vol / flow if flow else 0
            energy = energy_left
            constraints.append("energy budget reached")
        if dur < z.min_run_min:
            recs.append(Recommendation(z.zone_id, Mode.HOLD, 0, 0, 0, e.confidence, e.risk,
                                       reasons + [f"allowed run {dur:.1f} min is below minimum {z.min_run_min:.0f} min"], constraints))
            continue

        usable -= vol
        energy_left -= energy
        recs.append(Recommendation(z.zone_id, mode, round(vol, 1), round(dur, 1), round(energy, 3),
                                   e.confidence, e.risk, reasons, constraints))
    return sorted(recs, key=lambda r: r.zone_id)
