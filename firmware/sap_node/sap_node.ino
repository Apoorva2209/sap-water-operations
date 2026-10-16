/*
  SAP field node — ESP32 (Arduino core)
  Hardware safety layer for the 2-zone bench prototype.

  The node obeys simple serial commands from the edge controller
  (Raspberry Pi / laptop running `python3 -m sap.server`) but enforces its own
  safety limits locally, so a crashed controller or lost link can never leave
  the pump running.

  Serial protocol (115200 baud, newline-terminated):
    RUN <zone> <litres> <max_minutes>   start a run on zone A or B
    STOP                                stop everything
    STATUS                              print one JSON status line
  Node prints JSON lines:  {"evt":"status"|"tick"|"done"|"trip", ...}

  Wiring (example, adjust to your board):
    Relay pump           GPIO 26      Relay valve A  GPIO 27   Relay valve B  GPIO 14
    Flow sensor (YF-S201) GPIO 34 (interrupt, 7.5 pulses per L/min)
    Pressure transducer  GPIO 35 (0.5-4.5 V via divider)
    Pump current (ACS712) GPIO 32
    Tank level (ultrasonic) TRIG 5 / ECHO 18
    Soil A shallow/deep  GPIO 36 / 39   Soil B shallow/deep GPIO 33 / 25
    E-stop button        GPIO 4 (to GND, INPUT_PULLUP)
  !! Mains-powered pumps must be switched through a rated contactor installed by
  !! a qualified electrician. Keep electronics in an IP65 enclosure.
*/

#include <Arduino.h>

const int PIN_PUMP = 26, PIN_VALVE_A = 27, PIN_VALVE_B = 14;
const int PIN_FLOW = 34, PIN_PRESS = 35, PIN_CURR = 32, PIN_TRIG = 5, PIN_ECHO = 18, PIN_ESTOP = 4;
const int PIN_SOIL[2][2] = {{36, 39}, {33, 25}};

// ---- safety limits (calibrate on the bench) ----
const float NOMINAL_FLOW_LPM[2] = {24.0, 20.0};
const float NOMINAL_PRESSURE_KPA = 150.0;
const float MIN_TANK_CM_TO_EMPTY = 10.0;   // stop when water is this close to the intake
const float MIN_CURRENT_A = 1.0, MAX_CURRENT_A = 12.0;
const float LOW_FLOW_RATIO = 0.5, HIGH_FLOW_RATIO = 1.5, LOW_PRESS_RATIO = 0.5;
const unsigned long GRACE_MS = 20000;      // ignore start-up transients
const unsigned long HEARTBEAT_MS = 30000;  // stop if controller is silent this long during a run

volatile unsigned long flowPulses = 0;
void IRAM_ATTR onFlowPulse() { flowPulses++; }

int activeZone = -1;
float targetL = 0, deliveredL = 0;
unsigned long runStart = 0, maxRunMs = 0, lastTick = 0, lastHeard = 0;

float readPressureKpa() {
  float v = analogRead(PIN_PRESS) / 4095.0 * 3.3 * 1.5;    // divider ratio
  return max(0.0f, (v - 0.5f) / 4.0f * 1200.0f);           // 0-1.2 MPa sensor
}
float readCurrentA() {
  float v = analogRead(PIN_CURR) / 4095.0 * 3.3;
  return fabs((v - 1.65) / 0.066);                          // ACS712-30A on 3.3 V divider
}
float readTankGapCm() {
  digitalWrite(PIN_TRIG, LOW); delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(10); digitalWrite(PIN_TRIG, LOW);
  unsigned long d = pulseIn(PIN_ECHO, HIGH, 30000);
  return d ? d * 0.0343 / 2.0 : -1;                         // distance from sensor to water
}
float readSoil(int z, int depth) {                          // raw 0-1, calibrate per soil
  return 1.0 - analogRead(PIN_SOIL[z][depth]) / 4095.0;
}

void allOff() {
  digitalWrite(PIN_PUMP, LOW);
  delay(300);                                               // stop pump before closing valves
  digitalWrite(PIN_VALVE_A, LOW);
  digitalWrite(PIN_VALVE_B, LOW);
}

void finish(const char* evt, const char* reason) {
  allOff();
  Serial.printf("{\"evt\":\"%s\",\"zone\":\"%c\",\"delivered_l\":%.1f,\"reason\":\"%s\"}\n",
                evt, activeZone == 0 ? 'A' : 'B', deliveredL, reason);
  activeZone = -1;
}

void startRun(int zone, float litres, float maxMin) {
  if (activeZone >= 0) { Serial.println("{\"evt\":\"error\",\"msg\":\"busy\"}"); return; }
  if (digitalRead(PIN_ESTOP) == LOW) { Serial.println("{\"evt\":\"error\",\"msg\":\"estop active\"}"); return; }
  activeZone = zone; targetL = litres; deliveredL = 0;
  maxRunMs = (unsigned long)(maxMin * 60000.0); runStart = millis(); lastTick = runStart; lastHeard = runStart;
  noInterrupts(); flowPulses = 0; interrupts();
  digitalWrite(zone == 0 ? PIN_VALVE_A : PIN_VALVE_B, HIGH);
  delay(500);                                               // open valve before pump: no dead-heading
  digitalWrite(PIN_PUMP, HIGH);
  Serial.printf("{\"evt\":\"start\",\"zone\":\"%c\",\"target_l\":%.1f}\n", zone == 0 ? 'A' : 'B', litres);
}

void safetyTick() {
  unsigned long now = millis();
  if (now - lastTick < 1000) return;
  float dt = (now - lastTick) / 1000.0; lastTick = now;
  noInterrupts(); unsigned long p = flowPulses; flowPulses = 0; interrupts();
  float flow = (p / dt) / 7.5;                              // L/min
  deliveredL += flow * dt / 60.0;
  float press = readPressureKpa(), cur = readCurrentA(), gap = readTankGapCm();
  unsigned long t = now - runStart;
  float nf = NOMINAL_FLOW_LPM[activeZone];
  Serial.printf("{\"evt\":\"tick\",\"t_s\":%lu,\"flow_lpm\":%.1f,\"pressure_kpa\":%.0f,\"current_a\":%.1f,\"delivered_l\":%.1f}\n",
                t / 1000, flow, press, cur, deliveredL);

  if (digitalRead(PIN_ESTOP) == LOW) return finish("trip", "emergency stop");
  if (cur > MAX_CURRENT_A) return finish("trip", "pump overcurrent");
  if (gap > 0 && gap > 200 - MIN_TANK_CM_TO_EMPTY) return finish("trip", "tank below reserve");
  if (now - lastHeard > HEARTBEAT_MS) return finish("trip", "controller heartbeat lost");
  if (t > maxRunMs) return finish("trip", "max run time reached");
  if (t > GRACE_MS) {
    if (cur < MIN_CURRENT_A) return finish("trip", "dry-run suspected");
    if (flow < LOW_FLOW_RATIO * nf) return finish("trip", "low flow: blockage or dry source");
    if (flow > HIGH_FLOW_RATIO * nf) return finish("trip", "high flow: possible burst");
    if (press < LOW_PRESS_RATIO * NOMINAL_PRESSURE_KPA) return finish("trip", "pressure collapse");
  }
  if (deliveredL >= targetL) return finish("done", "target volume delivered");
}

void printStatus() {
  Serial.printf("{\"evt\":\"status\",\"active\":%d,\"tank_gap_cm\":%.0f,\"pressure_kpa\":%.0f,"
                "\"soil\":[[%.3f,%.3f],[%.3f,%.3f]],\"estop\":%d}\n",
                activeZone, readTankGapCm(), readPressureKpa(),
                readSoil(0, 0), readSoil(0, 1), readSoil(1, 0), readSoil(1, 1),
                digitalRead(PIN_ESTOP) == LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_PUMP, OUTPUT); pinMode(PIN_VALVE_A, OUTPUT); pinMode(PIN_VALVE_B, OUTPUT);
  allOff();                                                 // fail-safe default on boot
  pinMode(PIN_TRIG, OUTPUT); pinMode(PIN_ECHO, INPUT); pinMode(PIN_ESTOP, INPUT_PULLUP);
  pinMode(PIN_FLOW, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_FLOW), onFlowPulse, RISING);
  Serial.println("{\"evt\":\"boot\",\"node\":\"sap-node-1\"}");
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n'); line.trim();
    lastHeard = millis();
    if (line.startsWith("RUN ")) {
      char z; float l, m;
      if (sscanf(line.c_str(), "RUN %c %f %f", &z, &l, &m) == 3 && (z == 'A' || z == 'B') && l > 0 && m > 0 && m <= 120)
        startRun(z == 'A' ? 0 : 1, l, m);
      else Serial.println("{\"evt\":\"error\",\"msg\":\"bad RUN\"}");
    } else if (line == "STOP") {
      if (activeZone >= 0) finish("trip", "manual stop"); else allOff();
    } else if (line == "STATUS" || line == "PING") {
      printStatus();
    }
  }
  if (activeZone >= 0) safetyTick();
}
