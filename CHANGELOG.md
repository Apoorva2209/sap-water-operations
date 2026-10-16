# Changelog

## 0.1.0 - 2026-10-16

First tagged release.

- Decision engine: root-zone water-balance estimator with confidence, shared-source allocator, local safety interlocks, post-run verification and fault classification, hash-chained event log.
- Strategy simulator (timer vs threshold vs SAP) on a synthetic season. Simulated results only, not field evidence.
- Edge controller with simulated hardware, local web dashboard and JSON API (PIN-protected actions, localhost by default).
- ESP32 firmware for pump/valve control and sensing. Not yet run on real hardware.
- Tests, GitHub Actions CI (Python 3.10-3.12), MIT license.
