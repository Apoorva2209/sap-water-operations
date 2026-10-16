# SAP — offline-first water operations for farms sharing one source

[![tests](https://github.com/Apoorva2209/sap-water-operations/actions/workflows/tests.yml/badge.svg)](https://github.com/Apoorva2209/sap-water-operations/actions/workflows/tests.yml) [![license: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE) ![status: simulation + bench prototype](https://img.shields.io/badge/status-simulation%20%2B%20bench%20prototype-orange)

SAP helps a group of small farms (for example an FPO cluster on one borewell or tank) decide **where limited water should go, deliver it safely even without internet, and verify that it reached the root zone**.

Student venture · Sri Sairam Engineering College, Chennai · Wadhwani Foundation Ignite.

## Abstract

Small farms that share a single borewell, tank or canal outlet face a double problem: there is never enough water for every plot at the moment it is needed, and nobody can tell whether the water that was sent actually reached the roots. Fixed timers waste water on wet soil and starve dry plots; single-threshold controllers ignore weather, crop stage and the neighbour's needs; and both silently keep running through leaks, blockages and failed sensors. Most farm connectivity is also too weak for cloud-dependent systems.

SAP (Shared Agri Water Platform) is an offline-first water-operations system built around three ideas. First, **fair, explainable allocation**: an interpretable FAO-56 style root-zone water balance estimates each zone's need from two-depth soil moisture, evapotranspiration and forecast, attaches a confidence score with stated reasons, and then divides the limited source across zones by crop risk and agreed priority, within reserve, pump, run-time and energy limits. Confidence decides the mode: run automatically, ask the operator, run conservatively, hold, or inspect. Second, **safe delivery without internet**: every run executes on a local controller and an ESP32 node with independent interlocks (emergency stop, source reserve, dry-run, overcurrent, low/high flow, pressure collapse, lost-controller heartbeat). Third, **verification and accountability**: after each run SAP checks that the planned water flowed and that the soil responded, classifies likely leaks, blockages, stuck valves and sensor faults, locks the affected zone for inspection, and records recommendations, approvals, commands and results in a SHA-256 hash-chained log in which tampering is detectable.

The repository contains the decision engine, a strategy simulator, an edge controller with a local PIN-protected web dashboard that works on farm Wi-Fi, ESP32 firmware, tests and CI. On a synthetic 30-day season with injected faults, SAP used less water than a fixed timer (about 32% less) with fewer crop-stress days, and caught both injected faults that the timer and threshold strategies missed. **These are simulation results that test the logic, not field evidence**; the firmware has not yet run on real hardware. Next steps are bench calibration, a two-zone prototype and a paired control-plot field trial.

## From problem to solution

| # | The problem on a shared-source farm | How SAP solves it | Where |
|---|---|---|---|
| 1 | Not enough water for every plot at once; the loudest or nearest farmer wins | Splits the limited water by crop risk and agreed priority, within tank reserve, pump, run-time and energy limits | `allocator.py` |
| 2 | Nobody knows how much a plot really needs; timers and single thresholds ignore weather and crop stage | FAO-56 style root-zone water balance from 2-depth soil moisture, evapotranspiration and forecast | `estimator.py` |
| 3 | Bad sensors and stale forecasts cause wrong decisions that look confident | Every recommendation carries a confidence score and written reasons; low confidence means ask, run small, hold or inspect | `estimator.py`, `allocator.py` |
| 4 | Farm internet is weak or absent | Everything runs on a local controller and dashboard over farm Wi-Fi; approvals work offline | `controller.py`, `server.py` |
| 5 | Pumps burn out dry, pipes burst, valves stick | Local interlocks stop the run: e-stop, low tank, dry-run, overcurrent, low/high flow, pressure collapse; the ESP32 enforces them itself, including if the controller goes silent | `safety.py`, `sap_node.ino` |
| 6 | Water is sent but nobody checks it reached the roots; leaks go unnoticed | After each run SAP compares planned vs delivered water and expected vs measured soil response, then flags leak, blockage, stuck valve, dry-run, sensor fault or ineffective irrigation, and locks the zone for inspection | `verify.py` |
| 7 | Disputes between members: who got what, who approved it | Hash-chained log of recommendations, approvals, commands and results; editing any entry is detectable | `eventlog.py` |
| 8 | Hard to know if it is better than what farmers do now | Simulator compares fixed timer, threshold and SAP on the same synthetic season with injected faults | `simulator.py` |

**The flow in one line:** read sensors, estimate need and confidence, allocate shared water, run (or ask) according to confidence, stop on any unsafe condition, verify the result, log it.

**What is proven and what is not:** the logic is tested (unit tests and simulation). Real-world savings, sensor accuracy and the firmware on hardware are **not yet proven**; that needs bench calibration and a paired control-plot field trial.

## What is in this repository

| Module | What it does |
|---|---|
| `sap/models.py` | Data entities: zone, crop, soil, source, sensor reading, recommendation, measurement, verification |
| `sap/estimator.py` | Interpretable FAO-56 style root-zone water balance per zone, with a **confidence score and stated reasons** (sensor disagreement, missing depth, stale reading, stale forecast) |
| `sap/allocator.py` | Shares limited water across zones by crop risk and agreed priority, within source reserve, pump, run-time and energy limits. Chooses a mode: `auto`, `needs_approval`, `conservative`, `inspect`, `hold` |
| `sap/safety.py` | Local interlocks for every run: emergency stop, manual override, source reserve, dry-run (pump current), overcurrent, low/high flow, pressure collapse |
| `sap/verify.py` | After each run: did the planned water flow, and did soil respond as predicted? Flags likely leak, blockage, stuck valve, dry-run, sensor fault or ineffective irrigation |
| `sap/eventlog.py` | Append-only, SHA-256 hash-chained log of recommendations, approvals, commands and results; tampering is detectable |
| `sap/simulator.py` | Compares fixed timer, single moisture threshold and SAP on the same synthetic season with injected faults |
| `sap/controller.py` | Edge controller: daily plan, approvals, safe execution, verification, fault lockout (simulated hardware for demos) |
| `sap/server.py` + `sap/dashboard/index.html` | Local web dashboard and JSON API (stdlib only) — works on farm Wi-Fi with no internet; PIN-protected actions |
| `firmware/sap_node/sap_node.ino` | ESP32 node: pump/valve relays, flow, pressure, pump current, tank level, 2-depth soil, e-stop; enforces safety limits itself, incl. controller-heartbeat loss |
| `tests/test_sap.py` | Unit tests for estimation, allocation, safety, verification, the log and the simulator |

![SAP dashboard: zone cards, a leak detected and locked on zone C, verified event log](docs/dashboard.png)

*Dashboard with simulated hardware: a leak was injected on zone C, detected after the run and the zone locked for inspection.*

## Quick start

```bash
git clone https://github.com/Apoorva2209/sap-water-operations.git
cd sap-water-operations
pip install -e ".[test]"          # no runtime dependencies; pytest only for tests

sap-server                        # dashboard at http://localhost:8080 (demo PIN 1234)
sap-simulate                      # strategy comparison (simulated season)
python -m pytest -q               # run the tests
```

Equivalent without installing: `python -m sap.server`, `python -m sap.simulator`. Python 3.10+.

**Before using on a network:** set `SAP_PIN` to your own PIN. The server listens on localhost only; set `SAP_HOST=0.0.0.0` to serve the farm Wi-Fi (see [SECURITY.md](SECURITY.md)).

## Documentation

* [docs/API.md](docs/API.md) - dashboard JSON API and configuration
* [docs/HARDWARE.md](docs/HARDWARE.md) - ESP32 pin map, safety behaviour and bench checklist
* [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [CHANGELOG.md](CHANGELOG.md)

## Decision flow

1. Read 2-depth soil moisture, weather forecast, source level.
2. Estimate each zone's need and confidence (`estimator.py`).
3. Plan allocation under source/pump/energy limits and agreed priorities (`allocator.py`).
4. High confidence → run automatically; medium → operator approval; low → conservative run or hold; open fault → inspect.
5. Execute on the local controller with interlocks (`safety.py`) — works offline.
6. Verify delivery and soil response; classify faults (`verify.py`).
7. Log everything in a tamper-evident chain (`eventlog.py`); sync when online.

## Honest status

* **Simulation only.** The simulator uses a simple daily soil bucket and synthetic weather. Its numbers test the logic; they are **not** evidence of water savings or accuracy.
* **The firmware has not been run on real hardware.** The dashboard uses simulated hardware (`FakeHardware`). Calibrate sensors on the bench first and have an electrician wire any mains pump.
* No field data yet. ML is deliberately not used until there is data, an evaluation plan and a fallback.
* Thresholds (confidence cut-offs, fault ratios) are starting assumptions to be calibrated on the bench prototype and in a control-plot field trial.
* A patent/novelty search has not been done; no novelty is claimed.

## Next steps

* Bench prototype: 2 zones, shared tank, pump, valves, flow + pressure + pump-current sensing, ESP32/Raspberry Pi controller.
* SMS/WhatsApp approvals (the local web dashboard already exists).
* Field trial with paired SAP and control plots and an agronomist rating crop condition.
