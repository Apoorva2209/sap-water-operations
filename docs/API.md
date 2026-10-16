# Dashboard JSON API

The dashboard server (`python -m sap.server`) exposes a small JSON API on the
edge controller. Read endpoints need no PIN; every `POST` needs `"pin"` in the
JSON body (set with `SAP_PIN`).

| Method | Path | Body | Effect |
|---|---|---|---|
| GET | `/api/state` | | Tank level, zones (plan, reasons, limits, last verification), event log, `log_ok` |
| GET | `/api/simulate` | | Strategy comparison on the synthetic season |
| POST | `/api/approve` | `zone` | Start the recommended run (refused if another run is active) |
| POST | `/api/reject` | `zone` | Hold the zone |
| POST | `/api/auto` | | Start the first auto-approved zone |
| POST | `/api/replan` | | Recompute the plan |
| POST | `/api/estop` | `on` (bool) | Set or clear the emergency stop |
| POST | `/api/clear` | `zone` | Mark a fault repaired and release the lockout |
| POST | `/api/inject` | `kind` (`leak`/`blockage`/`sensor`), `zone` | Test only: inject a fault into the simulated hardware |
| POST | `/api/network` | `online` (bool) | Test only: simulate internet loss |
| POST | `/api/weather` | `rain_mm` | Test only: set the rain forecast |

Errors: `403` wrong PIN, `400` invalid input or nothing to approve, `404`
unknown path, `413` oversized body.

Configuration (environment variables): `SAP_PIN`, `SAP_PORT` (default 8080),
`SAP_HOST` (default `127.0.0.1`; use `0.0.0.0` to serve the farm Wi-Fi),
`SAP_LOG` (event log path, default `data/events.jsonl`).
