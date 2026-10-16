# Hardware and firmware (bench prototype)

> **Status: not yet run on real hardware.** Treat everything here as a design
> to validate on the bench. Calibrate every sensor first. Have a qualified
> electrician wire any mains-powered pump, and fit a hardware emergency stop
> and a fuse/MCB that do not depend on this software.

Firmware: `firmware/sap_node/sap_node.ino` (ESP32, Arduino framework).

## Pin map (as defined in the sketch)

| Function | ESP32 pin |
|---|---|
| Pump relay | GPIO 26 |
| Valve A relay | GPIO 27 |
| Valve B relay | GPIO 14 |
| Flow meter (pulse, interrupt) | GPIO 34 |
| Pressure sensor (analog, via divider) | GPIO 35 |
| Pump current sensor (analog) | GPIO 32 |
| Tank ultrasonic TRIG / ECHO | GPIO 5 / GPIO 18 |
| Emergency-stop button (to GND, pull-up) | GPIO 4 |
| Soil zone A shallow / deep | GPIO 36 / GPIO 39 |
| Soil zone B shallow / deep | GPIO 33 / GPIO 25 |

## Behaviour the node enforces on its own

The node stops the pump and closes valves if the controller goes silent
(heartbeat loss), the tank falls below reserve, the pump runs dry or draws too
much current, flow or pressure leaves the expected band, the run time is
exceeded, or the emergency stop is pressed.

## Bench checklist

1. Power the node with relays disconnected; check the serial `STATUS`/`PING` replies.
2. Calibrate flow (pulses per litre), pressure, current and tank-level conversions against reference measurements.
3. Dry-test relays with a lamp or low-voltage load, then water-test with a low-voltage pump.
4. Verify each trip (e-stop, heartbeat loss, dry-run, overcurrent, low/high flow) by deliberately causing it.
5. Only then connect the real pump, wired by an electrician.
6. Run a paired control-plot field trial before relying on any savings claim.
