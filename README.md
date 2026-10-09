# Home Privacy Agent

**Privacy-First Agentic Smart-Home Control with Fully Local Language Models on Commodity Hardware**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Hardware: ESP32](https://img.shields.io/badge/Hardware-ESP32-red.svg)](https://www.espressif.com/)

This repository provides the complete open-source code, edge firmware, escalation models, gateway daemon, and benchmark evaluation suite for **Home Privacy Agent**.

---

## 🏛️ System Architecture

Home Privacy Agent implements a zero-egress, two-tier architecture that guarantees life-safety reflexes while enabling deliberative reasoning using local small language models (SLMs):

```
+-----------------------------------------------------------------------------------------+
|                                    TRUSTED LOCAL LAN                                    |
|                                                                                         |
|  +--------------------------------+                  +-------------------------------+  |
|  |     Tier 0: ESP32 Edge Node    |                  |    Tier 1: Gateway Host PC    |  |
|  |   (~$0.70 testbed / ~$0.85 field) |                  |      (Consumer Laptop CPU)    |  |
|  |                                |                  |                               |  |
|  | * RTOS Life-Safety Reflex Task |  MQTT Port 1883  | * Mosquitto Message Broker    |  |
|  |   (<25 ms reaction time)       | <=============>  | * Gateway Orchestrator        |  |
|  | * Asymmetric Safety Envelope   |  home/digest     | * Ollama Engine (4-bit SLMs:  |  |
|  | * 16-Leaf Escalation Gate (C)  |  home/commands   |   1B, 3B, 7B parameters)      |  |
|  | * Local Clock Sink (home/time) |  home/time       | * 1 Hz Egress Audit Poller    |  |
|  +--------------------------------+                  +-------------------------------+  |
|                                                              |                          |
+--------------------------------------------------------------|--------------------------+
                                                               X  STRICT ZERO-EGRESS
                                                           [CLOUD / WAN BLOCKED]
```

1. **Tier 0 (Edge Reflex Layer):** Runs on ultra-low-cost ESP32 microcontrollers (~$0.70 testbed / ~$0.85 field). Executes a dedicated FreeRTOS safety task (Core 1, priority 3) enforcing hard life-safety reflexes (<25 ms reaction time) completely independent of network state. Includes a learned 16-leaf decision tree escalation gate compiled to 2 KB of C code that suppresses 99.3% of routine domestic telemetry.
2. **Asymmetric Actuation Envelope:** Firmware-verified grammar enforcement where safety-increasing actions (e.g., closing a gas valve, alerting a resident) are accepted, but safety-decreasing actions (e.g., opening a gas valve, disabling an alarm) are rejected by construction.
3. **Tier 1 (Deliberative Reasoning Layer):** Runs on consumer PC CPUs (e.g., Intel Core i7) hosting 4-bit quantized SLMs (Llama 3.2 1B/3B, Qwen 2.5 7B) through Ollama v0.3.12, executing structured multi-step tool calls over compact ~300-byte situation digests.
4. **Zero-Egress Auditing:** Continuous 1 Hz socket table polling (`egress_audit.py`) monitoring gateway and broker processes to verify that 0 bytes of model tokens or telemetry egress to non-RFC1918 networks. Microcontroller firmware contains no external DNS resolvers, remote NTP/SNTP clients, or HTTP libraries.

---

## 📁 Repository Structure

```
.
├── HARDWARE_SETUP.md          # Complete Bill of Materials, schematics, and wiring guide
├── START_HERE.md              # Interactive experiment reproduction walkthrough
├── requirements.txt           # Python dependencies
├── LICENSE                    # MIT License
└── code/
    ├── home_node/             # ESP32 FreeRTOS firmware sketch & C escalation model
    │   ├── home_node.ino
    │   └── escalation_model.h
    ├── home_node_bringup/     # Interactive hardware test & diagnostic sketch
    │   └── home_node_bringup.ino
    ├── laptop_agent/          # Evaluation harness, benchmark datasets & test tools
    │   ├── scenarios.json     # 24 formal evaluation scenarios across 3 families
    │   └── test_agent.py      # Offline harness for condition A, B, C, D, E runs
    ├── ml/                    # Escalation gate training, synthesis & export tools
    │   ├── train_escalation_gate.py
    │   ├── simulate_home.py
    │   └── results/           # Confusion matrices, tree rules & classification report
    ├── live_results/          # Logs and CSVs from live Hardware-in-the-Loop trials
    ├── results/               # 1 Hz egress monitoring logs
    ├── agent_system_prompt.md # Baseline prompt schema (v1)
    ├── agent_system_prompt_v2.md # Structured few-shot prompt schema (v2)
    ├── gateway_agent.py       # Live MQTT gateway broker & SLM orchestrator
    ├── run_live_campaign.py   # Automated 5-phase live hardware evaluation suite
    ├── analyze_live.py        # Statistical analysis and scoring tool
    ├── egress_audit.py        # Continuous 1 Hz host process socket auditor
    ├── mosquitto.conf         # Local-only MQTT broker configuration
    └── sim_node.py            # Software-simulated virtual node for CI testing
```

---

## ⚡ Quickstart Guide

### 1. Prerequisites
- **Python:** 3.10 or later
- **Ollama:** [Install Ollama](https://ollama.ai) (tested on v0.3.12)
- **Mosquitto:** [Install Eclipse Mosquitto](https://mosquitto.org/download/)
- **Arduino IDE:** [Install Arduino IDE](https://www.arduino.cc/en/software) with ESP32 board package 2.x/3.x

Install Python dependencies:
```bash
pip install -r requirements.txt
```

Pull the target open-weight local models via Ollama:
```bash
ollama pull llama3.2:1b
ollama pull llama3.2:3b
ollama pull qwen2.5:7b
```

---

### 2. Flashing the ESP32 Node
1. Connect the ESP32 board via USB.
2. Open `code/home_node/home_node.ino` in the Arduino IDE.
3. Install required Arduino libraries: `PubSubClient`, `ArduinoJson` (v7), and Adafruit `DHT sensor library`.
4. Configure your local Wi-Fi SSID and gateway host IP in lines 45–47:
   ```cpp
   #define WIFI_SSID   "YOUR_WIFI_SSID"
   #define WIFI_PASS   "YOUR_WIFI_PASSWORD"
   #define GATEWAY_IP  "192.168.137.1"
   ```
5. Select board **ESP32 Dev Module** and upload. Detailed wiring is documented in [HARDWARE_SETUP.md](HARDWARE_SETUP.md).

---

### 3. Launching the Local Zero-Egress Gateway
Start the local MQTT message broker:
```bash
mosquitto -c code/mosquitto.conf -v
```

Start the continuous 1 Hz process socket egress audit:
```bash
python code/egress_audit.py --minutes 60
```

Start the gateway agent orchestrator:
```bash
python code/gateway_agent.py --model qwen2.5:7b --prompt v2
```

---

### 4. Running the Benchmark Evaluations
To evaluate model performance across the 24 formal scenarios:

```bash
# Rule-based baseline (Condition A)
python code/laptop_agent/test_agent.py run --condition A

# Local SLM evaluation with prompt v2 (Condition D: Qwen 2.5 7B)
python code/laptop_agent/test_agent.py run --model qwen2.5:7b --prompt v2 --out results_7b.csv
```

To run the automated Hardware-in-the-Loop test campaign with a physical node:
```bash
python code/run_live_campaign.py --port COM5 --model qwen2.5:7b --prompt v2
```

---

## 🔒 Security & Privacy Guarantee

- **Zero Outbound Sockets:** Audited via 1 Hz process socket sampling (`code/egress_audit.py`).
- **Asymmetric Permission Boundary:** Rejecting safety-decreasing commands in hardware (`code/home_node/home_node.ino`).
- **Autonomous Local Reflex:** Deterministic gas cutoff and latching within 20.027 ms on-chip, guaranteed even when gateway host PC or local network is fully offline.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
