"""Edge controller: runs the daily cycle and executes approved runs safely.

In the prototype the hardware is simulated (`FakeHardware`); on the bench it is
replaced by a driver that talks to the ESP32 node over serial/MQTT with the same
methods. The controller keeps working with no network: approvals can also come
from the local dashboard or the physical buttons.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import asdict

from . import allocator, estimator, safety, verify
from .eventlog import EventLog
from .models import Fault, Measurement, Mode, SensorReading, Source, Weather
from .simulator import demo_farm


class FakeHardware:
    """Simulated tank, pump, valves and sensors for demos and tests."""

    def __init__(self, zones, seed=1):
        self.rng = random.Random(seed)
        self.zones = {z.zone_id: z for z in zones}
        self.vwc = {z.zone_id: z.soil.field_capacity * 0.7 for z in zones}
        self.tank_l = 4000.0
        self.faults = {"leak": None, "blockage": None, "sensor": None}
        self.open_valve = None

    def read_soil(self, zid):
        v = self.vwc[zid]
        n = lambda: round(v + self.rng.gauss(0, 0.006), 3)
        if self.faults["sensor"] == zid:
            return SensorReading(zid, n(), 0.58)          # deep probe stuck wet
        return SensorReading(zid, n() - 0.01, n())

    def tick(self, zid, t_s, dt_s):
        z = self.zones[zid]
        flow = z.valve_flow_lpm
        pressure = 150.0
        if self.faults["leak"] == zid:
            flow *= 1.45; pressure *= 0.55
        if self.faults["blockage"] == zid:
            flow *= 0.35; pressure *= 1.3
        litres = flow * dt_s / 60
        if self.tank_l <= 0:
            flow, litres = 0.0, 0.0
        self.tank_l = max(0.0, self.tank_l - litres)
        reached = litres * (0.45 if self.faults["leak"] == zid else 1.0)
        self.vwc[zid] += reached / z.area_m2 / z.crop.root_depth_mm
        current = 6.0 if self.tank_l > 0 else 0.4
        return safety.Tick(t_s, self.tank_l, flow, pressure, current), litres


class Controller:
    def __init__(self, log_path="data/events.jsonl", speed=60.0):
        self.zones = demo_farm()
        self.hw = FakeHardware(self.zones)
        self.log = EventLog(log_path)
        self.weather = Weather(et0_mm=5.2, rain_forecast_mm=0.0, age_h=3)
        self.online = True
        self.estop = False
        self.open_faults: set[str] = set()
        self.recs = {}
        self.ests = {}
        self.verifications = {}
        self.running = None
        self.speed = speed            # simulated seconds per real second
        self.lock = threading.RLock()
        self.plan()

    # ---------- planning ----------
    def source(self):
        return Source(self.hw.tank_l, 300, 40, 150, 0.35, 2.0)

    def plan(self):
        with self.lock:
            w = self.weather if self.online else Weather(self.weather.et0_mm, 0.0, 99)
            self.ests = {z.zone_id: estimator.estimate(z, self.hw.read_soil(z.zone_id), w) for z in self.zones}
            recs = allocator.plan(self.zones, self.ests, self.source(), self.open_faults)
            self.recs = {r.zone_id: r for r in recs}
            self.log.append("plan", {"recommendations": recs, "online": self.online})

    # ---------- operator actions ----------
    def approve(self, zid, actor="operator"):
        with self.lock:
            r = self.recs.get(zid)
            if not r or r.mode not in (Mode.NEEDS_APPROVAL, Mode.CONSERVATIVE, Mode.AUTO):
                return False, "nothing to approve"
            self.log.append("approval", {"zone": zid, "volume_l": r.volume_l}, actor=actor)
        threading.Thread(target=self._run, args=(zid,), daemon=True).start()
        return True, "started"

    def reject(self, zid, actor="operator"):
        with self.lock:
            self.log.append("rejection", {"zone": zid}, actor=actor)
            if zid in self.recs:
                self.recs[zid].mode = Mode.HOLD
        return True, "held"

    def emergency_stop(self, on=True, actor="operator"):
        self.estop = on
        self.log.append("emergency_stop" if on else "emergency_reset", {}, actor=actor)

    def clear_fault(self, zid, actor="technician"):
        with self.lock:
            self.open_faults.discard(zid)
            for k, v in self.hw.faults.items():
                if v == zid:
                    self.hw.faults[k] = None
            self.log.append("fault_cleared", {"zone": zid}, actor=actor)
        self.plan()

    def inject(self, kind, zid):
        self.hw.faults[kind] = zid
        self.log.append("fault_injected", {"kind": kind, "zone": zid}, actor="test")

    def run_auto(self):
        for zid, r in list(self.recs.items()):
            if r.mode == Mode.AUTO and not self.running:
                self.approve(zid, actor="controller")
                return zid
        return None

    # ---------- execution ----------
    def _run(self, zid):
        with self.lock:
            if self.running:
                return
            self.running = zid
        z = next(z for z in self.zones if z.zone_id == zid)
        r = self.recs[zid]
        before = self.hw.read_soil(zid)
        self.log.append("command", {"zone": zid, "action": "open_valve", "planned_l": r.volume_l})
        delivered, t, dt = 0.0, 0.0, 5.0
        flows, pressures, currents, trip = [], [], [], None
        while delivered < r.volume_l and t < z.max_run_min * 60:
            tick, litres = self.hw.tick(zid, t, dt)
            tick.estop = self.estop
            trip = safety.check(tick, z.valve_flow_lpm, 150)
            flows.append(tick.flow_lpm); pressures.append(tick.pressure_kpa); currents.append(tick.pump_current_a)
            delivered += litres
            if trip:
                break
            t += dt
            time.sleep(dt / self.speed)
        self.log.append("command", {"zone": zid, "action": "close_valve", "trip": trip})
        after = self.hw.read_soil(zid)
        m = Measurement(zid, round(delivered, 1), sum(flows) / len(flows), sum(pressures) / len(pressures),
                        sum(currents) / len(currents), before.vwc_shallow, after.vwc_shallow,
                        before.vwc_deep, after.vwc_deep)
        v = verify.verify(z, r, m, 150)
        if trip and v.fault == Fault.NONE:
            v.detail = f"stopped by safety: {trip}. " + v.detail
        with self.lock:
            self.verifications[zid] = {"verification": asdict(v), "measurement": asdict(m), "trip": trip}
            if v.fault not in (Fault.NONE,):
                self.open_faults.add(zid)
            self.log.append("verification", {"measurement": m, "result": v, "trip": trip})
            self.running = None
        self.plan()

    # ---------- view ----------
    def state(self):
        with self.lock:
            zones = []
            for z in self.zones:
                e, r = self.ests[z.zone_id], self.recs[z.zone_id]
                zones.append({
                    "id": z.zone_id, "member": z.member, "crop": z.crop.name, "soil": z.soil.name,
                    "area_m2": z.area_m2, "vwc": round(self.hw.vwc[z.zone_id], 3),
                    "fc": z.soil.field_capacity, "wp": z.soil.wilting_point,
                    "need_l": e.need_l, "confidence": e.confidence, "risk": e.risk,
                    "mode": r.mode.value, "volume_l": r.volume_l, "duration_min": r.duration_min,
                    "energy_kwh": r.energy_kwh, "reasons": r.reasons, "constraints": r.constraints,
                    "fault_open": z.zone_id in self.open_faults,
                    "last": self.verifications.get(z.zone_id),
                })
            ok, bad = self.log.verify_chain()
            return {"tank_l": round(self.hw.tank_l), "online": self.online, "estop": self.estop,
                    "running": self.running, "weather": asdict(self.weather), "zones": zones,
                    "log_ok": ok, "events": self.log.records()[-40:][::-1]}
