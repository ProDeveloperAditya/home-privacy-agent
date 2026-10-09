/*
 * home_node_bringup.ino — wiring test. Flash THIS first, before home_node.ino.
 * No Wi-Fi, no MQTT, no safety logic: it just proves every sensor and output works.
 *
 * Serial monitor 115200 baud. Every second it prints all inputs. Type a letter + Enter:
 *   v  toggle valve relay (GPIO16)      b  toggle buzzer (GPIO17)
 *   l  toggle lights (GPIO19)           k  toggle lock LED (GPIO18)
 * Expected: PIR flips 0/1 when you wave a hand (after ~60 s warm-up); DOOR flips when
 * you separate the reed switch from its magnet; STOVE_BTN / RESET_BTN read 0 while pressed;
 * GAS rises when you turn the potentiometer (emulated gas channel) - or when unlit lighter gas reaches a real MQ-2;
 * LDR falls when you cover it; temp/humidity look sane (~25-32 C, 40-80 %).
 * Libraries: DHT sensor library + Adafruit Unified Sensor.
 */
#include <DHT.h>
#define PIN_GAS 34
#define PIN_LDR 35
#define PIN_DHT 4
#define PIN_PIR 27
#define PIN_DOOR 26
#define PIN_STOVE_BTN 25
#define PIN_RESET_BTN 32
#define PIN_VALVE 16
#define PIN_BUZZER 17
#define PIN_LIGHTS 19
#define PIN_LOCK_LED 18
#define RELAY_ACTIVE_LOW 0        // must match home_node.ino; if the relay clicks ON at boot, set to 1

#define DHT_TYPE DHT11            // DHT22 if you have one
DHT dht(PIN_DHT, DHT_TYPE);
bool st[4] = {false, false, false, false};
const int outs[4] = {PIN_VALVE, PIN_BUZZER, PIN_LIGHTS, PIN_LOCK_LED};
const char keys[4] = {'v', 'b', 'l', 'k'};

void drive(int i) {
  bool level = st[i];
  if ((i == 0 || i == 2) && RELAY_ACTIVE_LOW) level = !level;   // relay channels
  digitalWrite(outs[i], level);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_PIR, INPUT); pinMode(PIN_DOOR, INPUT_PULLUP);
  pinMode(PIN_STOVE_BTN, INPUT_PULLUP); pinMode(PIN_RESET_BTN, INPUT_PULLUP);
  for (int i = 0; i < 4; i++) { pinMode(outs[i], OUTPUT); drive(i); }
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_GAS, ADC_11db); analogSetPinAttenuation(PIN_LDR, ADC_11db);
  dht.begin();
  Serial.println("bring-up ready. keys: v=valve b=buzzer l=lights k=lock-LED");
}

void loop() {
  static unsigned long t = 0;
  while (Serial.available()) {
    char c = Serial.read();
    for (int i = 0; i < 4; i++) if (c == keys[i]) { st[i] = !st[i]; drive(i); Serial.printf("%c -> %d\n", c, st[i]); }
  }
  if (millis() - t > 1000) {
    t = millis();
    Serial.printf("GAS=%4d LDR=%4d PIR=%d DOOR(open)=%d STOVE_BTN=%d RESET_BTN=%d  T=%.1fC H=%.0f%%\n",
                  analogRead(PIN_GAS), analogRead(PIN_LDR), digitalRead(PIN_PIR),
                  digitalRead(PIN_DOOR), !digitalRead(PIN_STOVE_BTN), !digitalRead(PIN_RESET_BTN),
                  dht.readTemperature(), dht.readHumidity());
  }
}
