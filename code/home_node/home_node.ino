/*
 * home_node.ino — Room node firmware (kitchen OR living room), v2.
 *
 *  TIER 0  (task "tier0", core 1, priority 3, 10 ms period)
 *          Hard-wired life-safety rules. No network, no model, no dependence on the
 *          Arduino loop() — a Wi-Fi/MQTT stall CANNOT delay it.
 *            gas/smoke >= GAS_ALARM_RAW  -> close valve relay + buzzer, LATCHED
 *            over-temperature            -> buzzer, LATCHED
 *          Latches clear ONLY via the physical RESET button (never over the network).
 *  ML GATE (loop task, once/minute)
 *          Computes 12 features, runs the exported decision tree (escalation_model.h)
 *          OR the gas-band safety net; if true, sends a JSON digest to the gateway.
 *  TIER 1  (gateway laptop, not here) answers with a command; onCommand() below is the
 *          ASYMMETRIC ENVELOPE: only safety-increasing verbs exist in this parser.
 *
 * HARDWARE VARIANT USED FOR THE PAPER'S PROTOTYPE (no relay module, no MQ-2, DHT11 not DHT22):
 *   - valve / lights "relays" are LEDs driven straight from the GPIO (RELAY_ACTIVE_LOW 0),
 *   - the gas channel on GPIO34 is EMULATED by a 10 k potentiometer (3V3 - wiper - GND); turning it
 *     raises the reading exactly like rising gas concentration (see GAS_EMULATED). The Tier-0 rule,
 *     its latency, the latch and the escalation logic are real; the sensor physics is not.
 *   - DHT11 (integer, +-2 C / +-5 % RH) replaces the DHT22.
 * Choose the variant with ONE define:  NODE_KITCHEN  or  NODE_LIVING.
 * Libraries (Arduino Library Manager): PubSubClient (Nick O'Leary), ArduinoJson v7,
 *   "DHT sensor library" (Adafruit) + "Adafruit Unified Sensor".
 * Board: "ESP32 Dev Module" (esp32 core 2.x or 3.x).  Serial monitor: 115200 baud.
 *
 * PINS (see HARDWARE_SETUP.md for the wiring diagram and the MQ-2 voltage divider!)
 *   GPIO34 MQ-2 AO via divider (ADC1, input-only)   GPIO35 LDR divider (ADC1)
 *   GPIO4  DHT22 data (10k pull-up)                 GPIO27 PIR out
 *   GPIO26 reed switch (INPUT_PULLUP, other leg GND) GPIO25 stove-on toggle button
 *   GPIO32 RESET/ACK button (INPUT_PULLUP)
 *   GPIO16 valve relay (kitchen)                    GPIO17 buzzer
 *   GPIO19 lights (relay ch2 kitchen / LED living)  GPIO18 door-lock LED (living)
 */
#define NODE_KITCHEN            // kitchen variant (gas channel + valve LED)
// #define NODE_LIVING

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include "escalation_model.h"

// ----------------------------- user configuration ---------------------------------
#define WIFI_SSID   "YOUR_WIFI_SSID"
#define WIFI_PASS   "YOUR_WIFI_PASSWORD"
#define GATEWAY_IP  "192.168.137.1"   // the laptop running mosquitto + Ollama (set a static IP / DHCP reservation)
#define RELAY_ACTIVE_LOW 0           // 0 for direct-drive LEDs (no relay board)
#define GAS_EMULATED 2               // 0 = real MQ-2 on GPIO34; 1 = potentiometer on GPIO34; 2 = level INJECTED over USB serial
                                     //     (keys 0-9 = 0..90 % of alarm, T = 130 %). Mode 2 = no gas hardware at all; label as emulated.
#define DOOR_BUTTON 1                // 1 = a push-button (GPIO26 to GND) stands in for the reed switch: PRESSED = door OPEN
#define DHT_TYPE DHT11               // DHT22 if you have one
#define GAS_ALARM_RAW  2400          // pot turned ~60 % of the way; with a real MQ-2 calibrate after burn-in
#define GAS_CLEAN_RAW   300          // raw ADC value with the pot fully counter-clockwise (0 % gas)
#define OVER_TEMP_C    65.0f

#ifdef NODE_KITCHEN
  #define NODE_ID "kitchen"
  #define HAS_GAS 1
#else
  #define NODE_ID "living"
  #define HAS_GAS 0
#endif

#define PIN_GAS 34
#define PIN_LDR 35
#define PIN_DHT 4
#define PIN_PIR 27
#define PIN_DOOR 26
#define PIN_STOVE_BTN 25
#define PIN_RESET_BTN 32
#define PIN_VALVE 18          // valve LED: the one working LED on this build (was GPIO16)
#define PIN_BUZZER 17
#define PIN_LIGHTS 19
#define PIN_LOCK_LED 16       // unused on this build (no LED fitted)

#if RELAY_ACTIVE_LOW
  #define RELAY_ON  LOW
  #define RELAY_OFF HIGH
#else
  #define RELAY_ON  HIGH
  #define RELAY_OFF LOW
#endif

// ----------------------------- shared state ---------------------------------------
WiFiClient net;
PubSubClient mqtt(net);
DHT dht(PIN_DHT, DHT_TYPE);

volatile int      gasRaw = 0;                // written by tier0 task
volatile bool     tripGas = false, tripTemp = false;
volatile uint32_t tier0LatencyUs = 0;        // threshold-crossing -> relay written
volatile bool     tripReport = false, resetReport = false;
volatile int      gasInject = GAS_CLEAN_RAW;
bool doorInject = false;                     // serial 'o' = door opened, 'c' = closed (no door hardware)             // GAS_EMULATED==2: raw ADC-equivalent value injected over serial        // set by tier0, printed by loop (Serial from a 10 ms task is avoided)
volatile float    tempC = NAN, humPct = NAN; // written by loop, read by tier0 (over-temp)

bool stoveOn = false, doorOpen = false, hvacSetAny = false;
float hvacSetpoint = 0;
unsigned long lightsOffAt = 0;
unsigned long lastMotionMs = 0, lastDoorMs = 0, lastDigestMs = 0, lastMinuteMs = 0;
bool recheckPending = false;
uint32_t motionEdges[20] = {0};              // per-minute PIR rising-edge counts (ring, 20 min)
uint8_t  minIdx = 0;
uint16_t motionThisMin = 0;
float gasHist[10] = {0};                     // gas_pct once/min for slope (ring, 10 min)
float humBase = NAN, ldrBase = NAN;          // slow baselines
float lastGas = -1, lastTemp = -1, lastHum = -1, lastLdr = -1;
uint16_t flatMin = 0;

// local time: beacon from the gateway (home/time). NO internet NTP -> zero-egress holds.
bool timeValid = false;
uint16_t baseMinOfDay = 12 * 60;
bool baseWeekday = true;
unsigned long baseMs = 0;

// ----------------------------- helpers --------------------------------------------
// Buzzer module on this build is ACTIVE-LOW and powered from 5 V, so a 3.3 V HIGH does not switch it fully off.
// ON  = drive the pin LOW.   OFF = release the pin (high-impedance); the module's pull-up keeps it silent.
static inline void buzz(bool on) { if (on) { pinMode(PIN_BUZZER, OUTPUT); digitalWrite(PIN_BUZZER, LOW); } else pinMode(PIN_BUZZER, INPUT); }
static inline void relay(int pin, bool on) { digitalWrite(pin, on ? RELAY_ON : RELAY_OFF); }
static inline float round1(float x) { return roundf(x * 10.0f) / 10.0f; }

uint16_t minuteOfDay() {
  return (baseMinOfDay + (millis() - baseMs) / 60000UL) % 1440;
}
float gasPct() { return 100.0f * (gasRaw - GAS_CLEAN_RAW) / (float)(GAS_ALARM_RAW - GAS_CLEAN_RAW); }

/* ===================== TIER 0 — hard-wired safety task ============================ */
void tier0Task(void *) {
  int ring[4] = {0}; uint8_t ri = 0; uint8_t over = 0; uint32_t tCross = 0;
  unsigned long resetHeldMs = 0;
  for (;;) {
#if HAS_GAS
#if GAS_EMULATED == 2
    ring[ri++ & 3] = gasInject;                // injected level goes through the SAME debounce/threshold/latch code
#else
    ring[ri++ & 3] = analogRead(PIN_GAS);
#endif
    int avg = (ring[0] + ring[1] + ring[2] + ring[3]) / 4;
    gasRaw = avg;
    if (avg >= GAS_ALARM_RAW) {
      if (over == 0) tCross = micros();
      if (++over >= 3 && !tripGas) {           // ~30 ms debounce, then act
        relay(PIN_VALVE, true);                // energise = CLOSE valve (demo relay/LED)
        buzz(true);
        tier0LatencyUs = micros() - tCross;
        tripGas = true; tripReport = true;
      }
    } else over = 0;
#endif
    if (!isnan(tempC) && tempC >= OVER_TEMP_C && !tripTemp) {
      buzz(true); tripTemp = true;
    }
    // Physical RESET: hold 2 s, and only if the hazard is actually gone.
    if (digitalRead(PIN_RESET_BTN) == LOW) {
      if (!resetHeldMs) resetHeldMs = millis();
      bool gasClear = !HAS_GAS || gasRaw < (GAS_CLEAN_RAW + 0.7f * (GAS_ALARM_RAW - GAS_CLEAN_RAW));
      bool tempClear = isnan(tempC) || tempC < OVER_TEMP_C - 5;
      if (millis() - resetHeldMs > 2000 && gasClear && tempClear) {
        relay(PIN_VALVE, false);               // valve reopens: physical action ONLY
        buzz(false);
        tripGas = tripTemp = false; resetHeldMs = 0; resetReport = true;
      }
    } else resetHeldMs = 0;
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

/* ===================== ASYMMETRIC COMMAND GRAMMAR ================================
   Safety-decreasing verbs (valve OPEN, door UNLOCK, buzzer OFF, sensor disable, any
   Tier-0 override) have NO branch here. They cannot be expressed, whatever the model,
   the gateway, or an attacker on the LAN sends. This is the paper's core claim.       */
void ack(const char *what, bool ok, const char *why) {
  JsonDocument d; d["node"] = NODE_ID; d["cmd"] = what; d["executed"] = ok; d["why"] = why;
  char b[200]; serializeJson(d, b); mqtt.publish("home/ack/" NODE_ID, b);
}

void onCommand(char *topic, byte *payload, unsigned int len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len)) return;

  if (strcmp(topic, "home/time") == 0) {                 // local time beacon
    baseMinOfDay = (d["hour"] | 12) * 60 + (d["min"] | 0);
    baseWeekday = d["weekday"] | true; baseMs = millis(); timeValid = true;
    return;
  }
  if (d["recheck"].is<const char *>()) { recheckPending = true; ack("recheck", true, "queued"); return; }

  const char *name = d["name"] | "", *state = d["state"] | "";
  int dur = d["duration_s"] | 0;
  if (dur < 0 || dur > 3600) { ack(name, false, "duration out of range"); return; }

  if (HAS_GAS && strcmp(name, "stove_valve") == 0 && strcmp(state, "closed") == 0) {
    relay(PIN_VALVE, true); ack(name, true, "closed");
  } else if (strcmp(name, "alarm_buzzer") == 0 && strcmp(state, "on") == 0) {
    buzz(true); ack(name, true, "on");   // only OFF path = physical RESET
  } else if (strcmp(name, "door_lock") == 0 && strcmp(state, "locked") == 0) {
    digitalWrite(PIN_LOCK_LED, HIGH); ack(name, true, "locked");
  } else if (strcmp(name, "lights") == 0 && (strcmp(state, "on") == 0 || strcmp(state, "off") == 0)) {
    bool on = state[1] == 'n';
    relay(PIN_LIGHTS, on); lightsOffAt = (on && dur) ? millis() + dur * 1000UL : 0;
    ack(name, true, state);
  } else if (strcmp(name, "hvac") == 0) {
    float sp = atof(state);
    if (sp >= 16 && sp <= 30) { hvacSetpoint = sp; hvacSetAny = true; ack(name, true, "setpoint"); }
    else ack(name, false, "hvac setpoint out of 16-30");
  } else {
    Serial.printf("[ENVELOPE] rejected: %s -> %s\n", name, state);
    ack(name, false, "not in command grammar");
  }
}

/* ===================== ML GATE + DIGEST ========================================== */
void computeFeatures(float f[GATE_N_FEATURES]) {
  uint16_t m = minuteOfDay();
  float slope = gasHist[minIdx % 10] - gasHist[(minIdx + 1) % 10];   // newest - oldest = pct per ~10 min
  uint32_t m20 = motionThisMin; for (int i = 0; i < 20; i++) m20 += motionEdges[i];   // incl. current partial minute
  f[0] = m / 60;                                   // hour
  f[1] = baseWeekday ? 1 : 0;                      // weekday
  f[2] = HAS_GAS ? gasPct() : 0;                   // gas_pct
  f[3] = slope;                                    // gas_slope
  f[4] = (isnan(humPct) || isnan(humBase)) ? 0 : humPct - humBase;    // hum_delta
  f[5] = isnan(tempC) ? 25 : tempC;                // temp_c
  f[6] = (millis() - lastMotionMs) / 60000UL;      // quiet_min
  f[7] = (lastDoorMs && millis() - lastDoorMs < 300000UL) ? 1 : 0;    // door_recent (5 min)
  f[8] = stoveOn ? 1 : 0;                          // stove_on
  f[9] = m20;                                      // motion_20
  f[10] = (isnan(ldrBase) || ldrBase < 1) ? 1 : analogRead(PIN_LDR) / ldrBase;  // light_ratio
  f[11] = flatMin;                                 // flat_min
}

const char *reasonFor(const float *f) {
  if (f[2] > 20 && f[2] < 60) return "gas/smoke sub-alarm level (creeping)";
  if (f[11] >= 30)            return "sensor flatline (identical readings)";
  if (f[9] >= 25)             return "implausible motion pattern on single sensor";
  if (f[7] > 0.5 && (f[0] >= 22 || f[0] <= 5)) return "unexpected door event at night";
  if (f[5] >= 32.5)           return "indoor temperature high";
  if (f[6] >= 240)            return "no motion for a long period";
  return "learned gate flagged unusual pattern";
}

void publishDigest(const float *f, const char *why) {
  JsonDocument d;
  uint16_t m = minuteOfDay();
  char tbuf[8]; snprintf(tbuf, sizeof tbuf, "%02d:%02d", m / 60, m % 60);
  d["node"] = NODE_ID;
  d["time"] = timeValid ? tbuf : "unknown";
  d["weekday"] = baseWeekday;
  JsonObject r = d["readings"].to<JsonObject>();
  if (HAS_GAS) { r[NODE_ID "_gas_pct_alarm"] = (int)f[2]; r[NODE_ID "_stove_on"] = stoveOn; }
  r[NODE_ID "_temp_c"] = round1(f[5]);
  r[NODE_ID "_humidity_delta_pct"] = round1(f[4]);
  r["motion_" NODE_ID "_min_ago"] = (int)f[6];
  r[NODE_ID "_motion_events_20min"] = (int)f[9];
  r[NODE_ID "_door"] = doorOpen ? "open" : "closed";
  r[NODE_ID "_light_ratio"] = round1(f[10]);
  r[NODE_ID "_flat_min"] = (int)f[11];
  d["occupancy_estimate"] = "unknown (single-node view)";
  d["escalation_reason"] = why;
  char buf[768]; serializeJson(d, buf);
  mqtt.publish("home/escalation", buf);
  Serial.printf("[ESCALATE] %s\n", buf);
}

char lastWhy[64] = "";                       // escalation back-off state (global so 'r' can reset it)
unsigned long backoffMs = 60000UL;

void rollMinute() {                          // roll per-minute rings and slow baselines
  minIdx = (minIdx + 1) % 20;
  motionEdges[minIdx] = motionThisMin; motionThisMin = 0;
  gasHist[minIdx % 10] = HAS_GAS ? gasPct() : 0;
  if (!isnan(humPct)) humBase = isnan(humBase) ? humPct : humBase + (humPct - humBase) / 60.0f;
  int ldr = analogRead(PIN_LDR);
  ldrBase = isnan(ldrBase) ? ldr : ldrBase + (ldr - ldrBase) / 1440.0f;
  // flatline detector: nothing moved beyond noise for N minutes (DHT11 is integer-valued, so any step counts)
  bool changed = fabsf(gasPct() - lastGas) > 1 || fabsf(tempC - lastTemp) > 0.2f ||
                 fabsf(humPct - lastHum) > 0.5f || abs(ldr - (int)lastLdr) > 10;
  flatMin = changed ? 0 : flatMin + 1;
  lastGas = gasPct(); lastTemp = tempC; lastHum = humPct; lastLdr = ldr;
}

// Evaluate the ML gate now. force=true (serial 'e', used by the campaign script) skips rate
// limit and back-off so a physical trial does not have to wait for the next minute tick.
void decide(bool force) {
  float f[GATE_N_FEATURES]; computeFeatures(f);
  bool gasBand = HAS_GAS && f[2] > 20 && f[2] < 60;           // safety net beside the tree
  bool esc = escalation_tree(f) || gasBand;
  // Escalation back-off: a condition that persists (e.g. a long quiet spell) must not wake the
  // model every minute. Same reason again -> wait 2x longer (cap 30 min; 5 min for gas creep,
  // which is safety-relevant). A different reason, or a recheck request, resets it.
  const char *why = recheckPending ? "gateway-requested sensor recheck" : reasonFor(f);
  bool same = strcmp(why, lastWhy) == 0 && !recheckPending;
  bool due = force || millis() - lastDigestMs > (same ? backoffMs : 60000UL);
  if (force) Serial.printf("[DECIDE] gate=%d gasband=%d reason=\"%s\"\n", escalation_tree(f), gasBand, why);
  if ((esc || recheckPending) && due) {
    unsigned long cap = (f[2] > 20 && f[2] < 60) ? 300000UL : 1800000UL;
    backoffMs = same ? min(backoffMs * 2, cap) : 60000UL;
    strncpy(lastWhy, why, sizeof lastWhy - 1);
    lastDigestMs = millis();
    publishDigest(f, why);
    recheckPending = false;
  }
}

void minuteTick() {
  rollMinute();
  float f[GATE_N_FEATURES]; computeFeatures(f);
  // One CSV line per minute = training data for re-fitting the gate on REAL data.
  Serial.printf("[FEAT],%s", NODE_ID);
  for (int i = 0; i < GATE_N_FEATURES; i++) Serial.printf(",%.2f", f[i]);
  Serial.println();
  decide(false);
}

void resetTrialState() {                     // serial 'r': clean slate between physical trials (Tier-0 latch untouched)
  lastWhy[0] = 0; backoffMs = 60000UL; lastDigestMs = 0; flatMin = 0; recheckPending = false;
  for (int i = 0; i < 20; i++) motionEdges[i] = 0;
  motionThisMin = 0; lastMotionMs = millis(); lastDoorMs = 0; stoveOn = false;
  humBase = humPct; lastGas = gasPct(); lastTemp = tempC; lastHum = humPct;
  gasInject = GAS_CLEAN_RAW; doorInject = false;
  Serial.println("[RESET] trial state cleared");
}

/* ===================== connectivity (non-blocking) =============================== */
void ensureNet() {
  static unsigned long lastTry = 0;
  if (WiFi.status() != WL_CONNECTED || mqtt.connected() || millis() - lastTry < 5000) return;
  lastTry = millis();
  if (mqtt.connect(NODE_ID, "home/status/" NODE_ID, 1, true, "{\"state\":\"offline\"}")) {
    mqtt.publish("home/status/" NODE_ID, "{\"state\":\"online\"}", true);
    mqtt.subscribe("home/command/" NODE_ID);
    mqtt.subscribe("home/time");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_PIR, INPUT); pinMode(PIN_DOOR, INPUT_PULLUP);
  pinMode(PIN_STOVE_BTN, INPUT_PULLUP); pinMode(PIN_RESET_BTN, INPUT_PULLUP);
  pinMode(PIN_VALVE, OUTPUT); relay(PIN_VALVE, false);
  buzz(false);
  pinMode(PIN_LIGHTS, OUTPUT); relay(PIN_LIGHTS, false);
  pinMode(PIN_LOCK_LED, OUTPUT); digitalWrite(PIN_LOCK_LED, LOW);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_GAS, ADC_11db); analogSetPinAttenuation(PIN_LDR, ADC_11db);
  dht.begin();
  lastMotionMs = millis();

  // Tier 0 first, independent of everything below (Wi-Fi may never come up).
  xTaskCreatePinnedToCore(tier0Task, "tier0", 4096, NULL, 3, NULL, 1);

  WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID, WIFI_PASS);
  mqtt.setServer(GATEWAY_IP, 1883); mqtt.setCallback(onCommand);
  mqtt.setBufferSize(768); mqtt.setSocketTimeout(2);
  Serial.println("node " NODE_ID " up. Serial: 'c' calibrate, 's' status, 'l' tier0 latency, 'e' evaluate gate now, 'r' reset trial state");
}

void serialTools() {
  if (!Serial.available()) return;
  char c = Serial.read();
  if (c == 'c' && HAS_GAS) {                       // MQ-2 calibration helper
    long sum = 0; int mn = 4095, mx = 0, n = 0; unsigned long t0 = millis();
    Serial.println("calibrating 60 s — keep sensor in CLEAN AIR, then repeat near an UNLIT lighter's gas");
    while (millis() - t0 < 60000) { int v = gasRaw; sum += v; n++; mn = min(mn, v); mx = max(mx, v); delay(100); }
    Serial.printf("clean-air raw: min=%d avg=%ld max=%d  -> set GAS_CLEAN_RAW~avg, GAS_ALARM_RAW between avg and gas-exposed value\n", mn, sum / n, mx);
  } else if (c == 's') {
    float f[GATE_N_FEATURES]; computeFeatures(f);
    for (int i = 0; i < GATE_N_FEATURES; i++) Serial.printf("f[%d]=%.2f ", i, f[i]);
    Serial.printf("\ngasRaw=%d trip=%d/%d wifi=%d mqtt=%d timeValid=%d\n", gasRaw, tripGas, tripTemp,
                  WiFi.status() == WL_CONNECTED, mqtt.connected(), timeValid);
  } else if (c == 'l') Serial.printf("last Tier-0 reaction: %u us\n", tier0LatencyUs);
  else if (GAS_EMULATED == 2 && ((c >= '0' && c <= '9') || c == 'T')) {
    int pct = (c == 'T') ? 130 : (c - '0') * 10;
    gasInject = GAS_CLEAN_RAW + (int)((GAS_ALARM_RAW - GAS_CLEAN_RAW) * pct / 100.0f);
    Serial.printf("[GAS] injected %d %% of alarm (raw %d)\n", pct, gasInject);
  }
  else if (c == 'o') { doorInject = true;  Serial.println("[DOOR] injected OPEN"); }
  else if (c == 'c') { doorInject = false; Serial.println("[DOOR] injected CLOSED"); }
  else if (c == 'k') { stoveOn = true;  Serial.println("[STOVE] injected ON"); }
  else if (c == 'e') decide(true);
  else if (c == 'r') resetTrialState();
}

void loop() {
  ensureNet(); mqtt.loop(); serialTools();
  unsigned long now = millis();
  if (resetReport) { resetReport = false; Serial.println("[TIER0] latch cleared by physical RESET"); }
  if (tripReport) { tripReport = false; Serial.printf("[TIER0] gas trip: reaction %u us, wifi=%d mqtt=%d\n", tier0LatencyUs, WiFi.status() == WL_CONNECTED, mqtt.connected()); }

  // fast inputs
  static bool pirPrev = false, btnPrev = true; static unsigned long dhtAt = 0;
  bool pir = digitalRead(PIN_PIR);
  if (pir) lastMotionMs = now;
  if (pir && !pirPrev) motionThisMin++;
  pirPrev = pir;
#if DOOR_BUTTON
  bool door = (digitalRead(PIN_DOOR) == LOW) || doorInject;   // button pressed (or injected over serial) = door open
#else
  bool door = digitalRead(PIN_DOOR) == HIGH;       // magnet apart = open
#endif
  if (door != doorOpen) { doorOpen = door; lastDoorMs = now; }
  bool btn = digitalRead(PIN_STOVE_BTN);           // manual stove-on toggle (demo/scripting)
  if (!btn && btnPrev) stoveOn = !stoveOn;
  btnPrev = btn;

  if (now - dhtAt > 2500) {                        // DHT22 min period is 2 s
    dhtAt = now;
    float t = dht.readTemperature(), h = dht.readHumidity();
    if (!isnan(t)) tempC = t;
    if (!isnan(h)) humPct = h;
  }
  if (lightsOffAt && now > lightsOffAt) { relay(PIN_LIGHTS, false); lightsOffAt = 0; }
  if (now - lastMinuteMs >= 60000UL) { lastMinuteMs = now; minuteTick(); }
  delay(20);
}
