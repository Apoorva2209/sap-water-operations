import tempfile

from sap import allocator, estimator, safety, verify
from sap.eventlog import EventLog
from sap.models import Fault, Measurement, Mode, Recommendation, SensorReading, Source, Weather
from sap.simulator import compare, demo_farm

Z = {z.zone_id: z for z in demo_farm()}
FRESH = Weather(et0_mm=5.0, rain_forecast_mm=0.0, age_h=2)


def src(avail=5000, energy=5.0):
    return Source(avail, 300, 40, 150, 0.35, energy)


def test_dry_zone_needs_water_with_high_confidence():
    z = Z["A"]
    e = estimator.estimate(z, SensorReading("A", 0.24, 0.25), FRESH)
    assert e.need_l > 0 and e.confidence >= 0.75


def test_rain_forecast_cancels_irrigation():
    z = Z["A"]
    e = estimator.estimate(z, SensorReading("A", 0.31, 0.32), Weather(5.0, 30.0, 2))
    assert e.need_l == 0


def test_stale_forecast_is_ignored_and_lowers_confidence():
    z = Z["A"]
    e = estimator.estimate(z, SensorReading("A", 0.31, 0.32), Weather(5.0, 30.0, 40))
    assert e.confidence < 1.0 and any("old" in r for r in e.reasons)


def test_sensor_disagreement_requires_approval():
    z = Z["B"]
    e = estimator.estimate(z, SensorReading("B", 0.07, 0.21), FRESH)
    recs = allocator.plan([z], {"B": e}, src())
    assert recs[0].mode in (Mode.NEEDS_APPROVAL, Mode.CONSERVATIVE, Mode.HOLD)
    assert recs[0].mode != Mode.AUTO


def test_allocation_respects_source_reserve():
    zones = list(Z.values())
    ests = {z.zone_id: estimator.estimate(z, SensorReading(z.zone_id, z.soil.wilting_point + 0.02,
                                                            z.soil.wilting_point + 0.02), FRESH) for z in zones}
    recs = allocator.plan(zones, ests, src(avail=1500))
    assert sum(r.volume_l for r in recs) <= 1500 - 300 + 1e-6


def test_open_fault_locks_zone():
    z = Z["C"]
    e = estimator.estimate(z, SensorReading("C", 0.14, 0.15), FRESH)
    recs = allocator.plan([z], {"C": e}, src(), open_faults={"C"})
    assert recs[0].mode == Mode.INSPECT and recs[0].volume_l == 0


def test_safety_trips():
    t = safety.Tick(t_s=60, tank_l=2000, flow_lpm=5, pressure_kpa=150, pump_current_a=6)
    assert "low flow" in safety.check(t, 24, 150)
    t = safety.Tick(t_s=60, tank_l=50, flow_lpm=24, pressure_kpa=150, pump_current_a=6)
    assert "reserve" in safety.check(t, 24, 150)
    t = safety.Tick(t_s=5, tank_l=2000, flow_lpm=24, pressure_kpa=150, pump_current_a=6, estop=True)
    assert "emergency" in safety.check(t, 24, 150)
    t = safety.Tick(t_s=60, tank_l=2000, flow_lpm=24, pressure_kpa=150, pump_current_a=6)
    assert safety.check(t, 24, 150) is None


def _rec(z, vol):
    return Recommendation(z.zone_id, Mode.AUTO, vol, vol / z.valve_flow_lpm, 0, 1, 1, [], [])


def test_verify_detects_leak_and_blockage():
    z = Z["C"]
    leak = Measurement("C", 600, 33, 80, 6, 0.15, 0.17, 0.15, 0.16)
    assert verify.verify(z, _rec(z, 600), leak, 150).fault == Fault.LEAK
    block = Measurement("C", 200, 10, 190, 6, 0.15, 0.152, 0.15, 0.151)
    assert verify.verify(z, _rec(z, 600), block, 150).fault == Fault.BLOCKAGE


def test_verify_ok_and_ineffective():
    z = Z["A"]
    rise = verify.predicted_rise(z, 800)
    ok = Measurement("A", 800, 24, 150, 6, 0.25, 0.25 + rise, 0.26, 0.26 + rise * 0.8)
    assert verify.verify(z, _rec(z, 800), ok, 150).fault == Fault.NONE
    flat = Measurement("A", 800, 24, 150, 6, 0.25, 0.25, 0.26, 0.26)
    assert verify.verify(z, _rec(z, 800), flat, 150).fault == Fault.INEFFECTIVE


def test_event_log_detects_tampering():
    with tempfile.TemporaryDirectory() as d:
        log = EventLog(f"{d}/events.jsonl")
        log.append("recommendation", {"zone": "A", "volume_l": 500})
        log.append("approval", {"zone": "A"}, actor="operator")
        assert log.verify_chain() == (True, None)
        lines = log.path.read_text().splitlines()
        lines[0] = lines[0].replace("500", "900")
        log.path.write_text("\n".join(lines) + "\n")
        assert log.verify_chain()[0] is False


def test_simulation_sap_finds_injected_faults():
    res = {r.strategy: r for r in compare()}
    assert res["sap"].faults_detected == res["sap"].faults_true == 2
    assert res["sap"].leaked_l < res["timer"].leaked_l
