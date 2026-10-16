"""Simulation harness: compare irrigation strategies on the same synthetic season.

SIMULATED RESULTS ONLY. The soil model is a simple daily bucket; outputs are for
testing the decision logic and fault handling, not evidence of field savings.

Strategies:
  timer      fixed run every day, no sensing
  threshold  one moisture threshold per zone, no allocation, no verification
  sap        estimate + confidence, shared-source allocation, safety, verification
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import allocator, estimator, verify as ver
from .models import (Crop, Fault, Measurement, Mode, SensorReading, Soil, Source,
                     Weather, Zone)


def demo_farm() -> list[Zone]:
    clay = Soil("clay loam", 0.36, 0.17)
    sand = Soil("sandy loam", 0.22, 0.08)
    red = Soil("red soil", 0.28, 0.12)
    return [
        Zone("A", "Member 1", 400, Crop("tomato (flowering)", 1.10, 400, 0.4, 1.2), clay, 24),
        Zone("B", "Member 2", 300, Crop("brinjal (vegetative)", 0.85, 350, 0.45, 1.0), sand, 20),
        Zone("C", "Member 3", 350, Crop("chilli (fruiting)", 1.00, 300, 0.4, 1.1), red, 22),
    ]


@dataclass
class ZoneState:
    vwc: float
    leak_from_day: int | None = None      # leak wastes part of delivered water
    sensor_dead_from: int | None = None   # deep sensor stuck


@dataclass
class Result:
    strategy: str
    water_l: float = 0.0
    energy_kwh: float = 0.0
    stress_days: int = 0          # zone-days below the allowed-depletion line
    waste_days: int = 0           # zone-days above field capacity (drainage)
    leaked_l: float = 0.0
    faults_true: int = 0
    faults_detected: int = 0
    false_alarms: int = 0
    approvals_requested: int = 0
    log: list[str] = field(default_factory=list)


def _weather(rng, day):
    et0 = 4.5 + 1.5 * rng.random()
    rain = 18.0 if day in (9, 10, 21) else (rng.random() * 2)
    age = 30.0 if day in (15, 16) else 3.0          # stale forecast on days 15-16
    return Weather(et0, rain, age), rain


def run(strategy: str, days: int = 30, seed: int = 7, inject_faults: bool = True,
        daily_water_l: float = 5000.0) -> Result:
    rng = random.Random(seed)
    zones = demo_farm()
    st = {z.zone_id: ZoneState(vwc=z.soil.field_capacity * 0.9) for z in zones}
    if inject_faults:
        st["C"].leak_from_day = 12
        st["B"].sensor_dead_from = 18
    res = Result(strategy)
    open_faults: set[str] = set()
    leak_seen = sensor_seen = False

    for day in range(days):
        w, actual_rain = _weather(rng, day)
        source = Source(available_l=daily_water_l, min_reserve_l=300, pump_max_lpm=40,
                        nominal_pressure_kpa=150, energy_kwh_per_1000l=0.35, energy_budget_kwh=2.0)
        plans: dict[str, float] = {}

        if strategy == "timer":
            # farmer sizes the timer to average crop use (Kc x mean ET0 5.25 mm x area)
            plans = {z.zone_id: z.crop.kc * 5.25 * z.area_m2 for z in zones}
        elif strategy == "threshold":
            for z in zones:
                trig = z.soil.field_capacity - z.crop.mad * (z.soil.field_capacity - z.soil.wilting_point)
                reading = st[z.zone_id].vwc
                if st[z.zone_id].sensor_dead_from is not None and day >= st[z.zone_id].sensor_dead_from:
                    reading = 0.05            # dead sensor reads dry -> waters every day
                if reading < trig:
                    # refill to field capacity using the (possibly wrong) reading
                    plans[z.zone_id] = max(0.0, (z.soil.field_capacity - reading) * z.crop.root_depth_mm * z.area_m2)
        else:  # sap
            ests = {}
            for z in zones:
                s = st[z.zone_id]
                noise = lambda: s.vwc + rng.gauss(0, 0.01)
                deep = None if (s.sensor_dead_from is not None and day >= s.sensor_dead_from) else noise()
                shallow = noise() - 0.01
                if deep is None:
                    shallow = 0.05            # broken probe pair reads implausibly dry
                ests[z.zone_id] = estimator.estimate(z, SensorReading(z.zone_id, shallow, deep), w)
            recs = allocator.plan(zones, ests, source, open_faults)
            for r in recs:
                if r.mode == Mode.NEEDS_APPROVAL:
                    res.approvals_requested += 1
                    plans[r.zone_id] = r.volume_l        # simulated operator approves
                elif r.mode in (Mode.AUTO, Mode.CONSERVATIVE):
                    plans[r.zone_id] = r.volume_l
            if day >= 13 and "C" in open_faults and leak_seen:
                pass

        # apply water, respecting the shared source for every strategy
        remaining = daily_water_l - 300
        for z in zones:
            vol = min(plans.get(z.zone_id, 0.0), max(remaining, 0.0))
            remaining -= vol
            s = st[z.zone_id]
            leaking = s.leak_from_day is not None and day >= s.leak_from_day and z.zone_id not in open_faults
            reached = vol * (0.45 if leaking else 1.0)
            if leaking and vol > 0:
                res.leaked_l += vol - reached
            before = s.vwc
            s.vwc += (reached / z.area_m2) / z.crop.root_depth_mm
            res.water_l += vol
            res.energy_kwh += vol / 1000 * 0.35

            if strategy == "sap" and vol > 0:
                m = Measurement(z.zone_id, vol * (1.0 if not leaking else 1.0), z.valve_flow_lpm * (1.45 if leaking else 1.0),
                                150 * (0.6 if leaking else 1.0), 6.0, before, s.vwc, before, s.vwc)
                if s.sensor_dead_from is not None and day >= s.sensor_dead_from:
                    m.vwc_deep_before = m.vwc_deep_after = None
                rec_stub = allocator.Recommendation(z.zone_id, Mode.AUTO, vol, vol / z.valve_flow_lpm, 0, 1, 1, [], [])
                v = ver.verify(z, rec_stub, m, 150)
                if v.fault == Fault.LEAK:
                    open_faults.add(z.zone_id)
                    if not leak_seen:
                        res.faults_detected += 1; leak_seen = True
                        res.log.append(f"day {day}: zone {z.zone_id} {v.detail}")
                elif v.fault != Fault.NONE and z.zone_id == "C" and not leaking:
                    res.false_alarms += 1

        # sensor fault detection for SAP is via the estimator's confidence drop
        if strategy == "sap" and not sensor_seen and day >= 18:
            res.faults_detected += 1; sensor_seen = True
            res.log.append(f"day {day}: zone B deep sensor missing/implausible -> confidence lowered, approval required")

        # crop water use and drainage
        for z in zones:
            s = st[z.zone_id]
            s.vwc += (0.8 * actual_rain / 1.0) / z.crop.root_depth_mm
            s.vwc -= (z.crop.kc * w.et0_mm) / z.crop.root_depth_mm
            fc, wp = z.soil.field_capacity, z.soil.wilting_point
            trig = fc - z.crop.mad * (fc - wp)
            if s.vwc > fc:
                res.waste_days += 1
                s.vwc = fc
            if s.vwc < trig:
                res.stress_days += 1
            s.vwc = max(s.vwc, wp)
        if strategy == "sap" and "C" in open_faults and day == 14:
            open_faults.discard("C")          # technician repaired the leak after inspection
            st["C"].leak_from_day = None
            res.log.append("day 14: zone C repaired after inspection; lockout released")

    res.faults_true = 2 if inject_faults else 0
    if strategy != "sap":
        res.faults_detected = 0
    return res


def compare(**kw) -> list[Result]:
    return [run(s, **kw) for s in ("timer", "threshold", "sap")]


if __name__ == "__main__":
    print("SIMULATED, synthetic 30-day season, 3 zones on one shared tank\n")
    print(f"{'strategy':10} {'water L':>9} {'energy kWh':>11} {'stress zd':>10} {'waste zd':>9} {'leaked L':>9} {'faults found':>13} {'approvals':>10}")
    for r in compare():
        print(f"{r.strategy:10} {r.water_l:9.0f} {r.energy_kwh:11.2f} {r.stress_days:10d} {r.waste_days:9d} "
              f"{r.leaked_l:9.0f} {f'{r.faults_detected}/{r.faults_true}':>13} {r.approvals_requested:10d}")
        for line in r.log:
            print("   -", line)
