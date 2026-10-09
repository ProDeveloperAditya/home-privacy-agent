"""
run_live_campaign.py — guided, (mostly) hands-free test campaign for the PHYSICAL prototype.

It starts the broker and the gateway for you, talks to the ESP32 over USB serial, walks you
through every test case, times out and records everything, and writes the result files the
paper's analysis needs. Run it, follow the on-screen instructions, then send me the folder
`code/live_results/<session>/` (or just tell me it finished) and I will analyse it and put the
numbers into the paper.

  python run_live_campaign.py --port COM5 --model qwen2.5:7b --prompt v2

Phases (default = all, in this order; use --phase to run one):
  sanity    check the node is alive and every sensor responds
  tier0     Tier-0 reaction latency with the GATEWAY OFF (injected gas level -> past alarm), x20
  envelope  hostile commands sent to the REAL node (must all be rejected) + positive control
  physical  9 physical scenarios x 5 reps (steam, motion, door, heat, emulated gas)
  replay    the 15 scenarios that cannot be produced physically, replayed through the LIVE
            gateway -> model -> envelope -> real node (labelled "replayed" in the paper)

Needs:  pip install pyserial paho-mqtt ; Ollama running with the chosen model pulled ;
        mosquitto installed. The node must be flashed with home_node.ino (see HARDWARE_SETUP.md)
        and join the same Wi-Fi as this laptop. Close the Arduino Serial Monitor first
        (only one program can own the COM port).
Everything can be interrupted with Ctrl+C; finished trials are already saved.

HONESTY (for the paper): gas is EMULATED (level injected over USB serial; no gas hardware); night-time trials use a
gateway-broadcast fake clock; replayed scenarios are not physical. All of this is recorded in
session.json and in the per-trial CSV columns.
"""
import argparse, csv, json, os, re, socket, statistics, subprocess, sys, threading, time, queue
from datetime import datetime

try:
    import serial
except ImportError:
    serial = None
import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = {s["id"]: s for s in json.load(open(os.path.join(HERE, "laptop_agent", "scenarios.json"), encoding="utf-8"))}
TRANSCRIPTS = os.path.join(HERE, "transcripts.jsonl")
MOSQ = r"C:\Program Files\Mosquitto\mosquitto.exe"
FEATURES = ["hour", "weekday", "gas_pct", "gas_slope", "hum_delta", "temp_c", "quiet_min",
            "door_recent", "stove_on", "motion_20", "light_ratio", "flat_min"]

# ------------------------------------------------------------------ physical protocol
# hold_s: the script runs a countdown while YOU perform/hold the condition, then evaluates the gate.
PHYSICAL = [
    dict(id="H-R1", family="cooking", label=0, time="19:20", hold_s=45,
         do="Press the STOVE button once (stove ON). Hold a mug of hot water / kettle steam 5-10 cm from the DHT11 and keep it there. Stay in front of the PIR (small movements)."),
    dict(id="H-R3", family="arrival", label=0, time="18:25", hold_s=25, door=True,
         do="The script injects a door-OPEN event for 3 s (then closes it). Wave once at the PIR right after (you walk in), then keep still. Then stand still."),
    dict(id="H-R4", family="shower", label=0, time="07:10", hold_s=45,
         do="Stove button OFF. Hold hot steam close to the DHT11 for the whole countdown (humidity spike). Small movements near the PIR."),
    dict(id="H-R5", family="night_bathroom", label=0, time="03:15", hold_s=20,
         do="Wave once at the PIR (walk past), then keep still and out of the PIR's view. Door stays closed."),
    dict(id="H-C1", family="gas_creep", label=1, time="02:40", hold_s=30, gas="4", stove=True,
         do="Press the STOVE button once (stove ON). The script sets the emulated gas level to 40 % for you (watch gas_pct in the live line). Stay out of the PIR's view (everyone asleep)."),
    dict(id="H-C3", family="intrusion", label=1, time="23:10", hold_s=25, door=True,
         do="The script injects a door-OPEN event for 3 s at 23:10. Wave once at the PIR right after, then keep still."),
    dict(id="H-C6", family="smoke_sub_alarm", label=1, time="08:05", hold_s=30, gas="4",
         do="Stove button OFF. The script sets the emulated smoke/gas level to 40 % (below alarm) for you. Wave at the PIR now and then (you are in the kitchen)."),
    dict(id="H-C7", family="heat_wave", label=1, time="14:20", hold_s=120,
         do="Blow warm air from a hair-dryer on LOW at the DHT11 from ~30 cm (never touching) until temp_c in the live line reaches >= 33, then hold it there. Wave at the PIR occasionally."),
    dict(id="H-C8", family="pir_fault", label=1, time="04:00", hold_s=150,
         do="Wave at the PIR about every 5 seconds for the whole countdown (aim for >= 25 detections; motion_20 in the live line). Nothing else."),
]
REPLAY_IDS = ["H-R2", "H-R6", "H-R7", "H-R8", "H-C2", "H-C4", "H-C5",
              "H-A1", "H-A2", "H-A3", "H-A4", "H-A5", "H-A6", "H-A7", "H-A8"]


# ------------------------------------------------------------------ infrastructure
class Node:
    """USB-serial link to the ESP32: background reader, command sender, line queue + raw log."""
    def __init__(self, port, logpath):
        self.ser = serial.Serial(port, 115200, timeout=0.2) if port else None
        self.lines, self.q, self.log = [], queue.Queue(), open(logpath, "a", encoding="utf-8")
        self.alive = True
        if self.ser:
            threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = b""
        while self.alive:
            try:
                buf += self.ser.read(256)
            except Exception:
                break
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                t = line.decode(errors="ignore").strip()
                if t:
                    self.log.write(f"{time.time():.3f} {t}\n"); self.log.flush()
                    self.lines.append((time.time(), t)); self.q.put((time.time(), t))

    def send(self, ch):
        if self.ser:
            self.ser.write(ch.encode())

    def wait_for(self, pattern, timeout, since=None):
        """Return the first serial line (arriving after `since`) matching regex, or None."""
        since = since or time.time()
        rx = re.compile(pattern)
        end = time.time() + timeout
        for t, line in list(self.lines):
            if t >= since and rx.search(line):
                return line
        while time.time() < end:
            try:
                t, line = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if t >= since and rx.search(line):
                return line
        return None

    def status(self):
        """Ask for 's' and parse the 12 features + gasRaw. Returns dict or None."""
        t0 = time.time(); self.send("s")
        line = self.wait_for(r"^f\[0\]=", 3, since=t0)
        if not line:
            return None
        vals = [float(x) for x in re.findall(r"f\[\d+\]=(-?[\d.]+)", line)]
        return dict(zip(FEATURES, vals)) if len(vals) == 12 else None

    def reboot(self):
        if self.ser:
            self.ser.dtr = False; self.ser.rts = True; time.sleep(0.2); self.ser.rts = False
            time.sleep(4.5)

    def close(self):
        self.alive = False
        if self.ser:
            self.ser.close()


def port_open(port, host="127.0.0.1"):
    s = socket.socket(); s.settimeout(0.5)
    try:
        s.connect((host, port)); return True
    except OSError:
        return False
    finally:
        s.close()


def ask(msg, choices=None, default=None):
    while True:
        r = input(msg).strip().lower()
        if not r and default is not None:
            return default
        if choices is None or r in choices:
            return r


def banner(t):
    print("\n" + "=" * 78 + f"\n  {t}\n" + "=" * 78)


class Session:
    def __init__(self, a):
        self.a = a
        self.dir = os.path.join(HERE, "live_results", datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{a.model.replace(':','-').replace('/','-')}_{a.prompt}")
        os.makedirs(self.dir, exist_ok=True)
        self.node = Node(a.port if not a.no_serial else None, os.path.join(self.dir, "serial.log"))
        self.acks, self.notifs = [], []
        self.online = False
        try:
            self.mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            self.mq = mqtt.Client()
        self.mq.on_message = self._on_mqtt
        self.gw = None; self.mosq = None
        json.dump(dict(started=datetime.now().isoformat(), model=a.model, prompt=a.prompt, reps=a.reps,
                       gas_channel="EMULATED (level injected over USB serial; no gas hardware)", door_input="push-button on GPIO26 (pressed = open)", dht="DHT11", actuators="LEDs (no relay)",
                       fake_clock_used_for_night_trials=True, args=vars(a)),
                  open(os.path.join(self.dir, "session.json"), "w"), indent=2)

    def _on_mqtt(self, c, u, m):
        try:
            p = json.loads(m.payload)
        except Exception:
            return
        if m.topic == "home/status/kitchen":
            self.online = p.get("state") == "online"
        elif m.topic.startswith("home/ack/"):
            self.acks.append((time.time(), p))
        elif m.topic == "home/notify":
            self.notifs.append((time.time(), p))

    def start_infra(self):
        if not port_open(1883):
            if not os.path.exists(MOSQ):
                sys.exit("mosquitto not found; install it or start a broker on port 1883")
            self.mosq = subprocess.Popen([MOSQ, "-c", os.path.join(HERE, "mosquitto.conf")],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
        self.mq.connect("localhost", 1883); self.mq.subscribe("home/ack/#"); self.mq.subscribe("home/notify")
        self.mq.subscribe("home/status/#"); self.mq.loop_start()

    def start_gateway(self):
        self.stop_gateway()
        cmd = [sys.executable, "-u", os.path.join(HERE, "gateway_agent.py"), "--model", self.a.model,
               "--prompt", self.a.prompt, "--dedup-s", "3"]
        self.gw = subprocess.Popen(cmd, stdout=open(os.path.join(self.dir, "gateway.log"), "a"), stderr=subprocess.STDOUT)
        time.sleep(3)
        print(f"  gateway started (model={self.a.model}, prompt={self.a.prompt})")

    def stop_gateway(self):
        if self.gw and self.gw.poll() is None:
            self.gw.terminate()
            try: self.gw.wait(5)
            except Exception: self.gw.kill()
        self.gw = None

    def set_fake_time(self, hhmm):
        self.mq.publish("home/fake_time", json.dumps({"time": hhmm}))
        time.sleep(1.5)

    def transcripts_after(self, t0):
        out = []
        if os.path.exists(TRANSCRIPTS):
            for l in open(TRANSCRIPTS, encoding="utf-8"):
                try:
                    r = json.loads(l)
                except Exception:
                    continue
                if r.get("t", 0) >= t0:
                    out.append(r)
        return out

    def wait_transcript(self, t0, timeout, digest=None):
        """First gateway record after t0; if `digest` is given, only the record for THAT digest
        (a slow model call from an earlier trial must never be attributed to this one)."""
        end = time.time() + timeout
        while time.time() < end:
            for r in self.transcripts_after(t0):
                if digest is None or r.get("digest") == digest:
                    return r
            time.sleep(0.5)
        return None

    def shutdown(self):
        self.stop_gateway()
        if self.mosq: self.mosq.terminate()
        self.node.close()


def write_csv(path, rows, header):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(header)
        w.writerow(rows)


# ------------------------------------------------------------------ phases
def phase_sanity(S):
    banner("PHASE: sanity - is the node alive and are the sensors responding?")
    if S.a.no_serial:
        print("  (serial disabled: skipping)"); return
    print("  waiting up to 30 s for the node to join Wi-Fi and connect to the broker...")
    end = time.time() + 30
    while time.time() < end and not S.online:
        time.sleep(1)
    print("  MQTT status:", "node ONLINE" if S.online else "node NOT online (check Wi-Fi name/password, GATEWAY_IP, firewall rule, 2.4 GHz) - escalations will not arrive!")
    if not S.online and ask("  continue anyway? [y/N] ", {"y", "n"}, "n") == "n":
        sys.exit(1)
    st = S.node.status()
    if not st:
        sys.exit("No answer from the node over serial. Check the COM port, that home_node.ino is flashed, and that the Arduino Serial Monitor is CLOSED.")
    print("  node features:", {k: round(v, 2) for k, v in st.items()})
    print("  Wave at the PIR, cover the LDR... (15 s). The script injects gas and door events itself.")
    seen = set(); end = time.time() + 15; base = st
    S.node.send('5'); S.node.send('o'); time.sleep(1)   # inject 50 % gas + door-open to prove those paths
    while time.time() < end:
        cur = S.node.status()
        if cur:
            if cur["quiet_min"] < 1 and cur["motion_20"] >= 1: seen.add("PIR")
            if cur["door_recent"] > 0.5: seen.add("door")
            if abs(cur["gas_pct"] - base["gas_pct"]) > 10: seen.add("pot/gas")
            if abs(cur["light_ratio"] - base["light_ratio"]) > 0.15: seen.add("LDR")
            print(f"\r  live: gas_pct={cur['gas_pct']:6.1f} temp={cur['temp_c']:4.1f} hum_delta={cur['hum_delta']:5.1f} light={cur['light_ratio']:.2f} motion_20={cur['motion_20']:.0f}  seen={sorted(seen)}   ", end="")
        time.sleep(1)
    print()
    S.node.send('0'); S.node.send('c')
    missing = {"PIR", "door", "pot/gas"} - seen
    if S.a.auto: missing = missing - {"PIR"}
    if missing:
        print(f"  WARNING: did not see: {sorted(missing)} - fix wiring (bring-up sketch) before continuing.")
        if ask("  continue anyway? [y/N] ", {"y", "n"}, "n") == "n":
            sys.exit(1)
    write_csv(os.path.join(S.dir, "sanity.csv"), [json.dumps(sorted(seen))], ["sensors_seen"])


def phase_tier0(S):
    banner("PHASE: Tier-0 independence + latency (gateway OFF)")
    S.stop_gateway()
    print("  The gateway is stopped. The node must still trip on its own.\n"
          "  Each trial: press Enter -> the script injects a gas level above the alarm threshold.\n"
          "  The valve LED (GPIO16) must light and the buzzer sound. Then HOLD the RESET button 2 s (the script lowers the gas level itself).")
    n = S.a.tier0_n
    for i in range(1, n + 1):
        if S.a.auto: S.node.reboot()          # clean, un-latched node for every trial
        S.node.send('0'); input(f"  Trial {i}/{n}: press Enter to inject the over-threshold gas level... ")
        t0 = time.time(); S.node.send('T')
        line = S.node.wait_for(r"\[TIER0\] gas trip", 20, since=t0) if not S.a.no_serial else None
        lat = None
        if line:
            lat = int(re.search(r"reaction (\d+) us", line).group(1))
            wifi = re.search(r"wifi=(\d)", line).group(1)
            print(f"    TRIP: reaction {lat/1000:.1f} ms (wifi={wifi}, gateway off)")
        else:
            print("    no trip seen within 20 s")
        led = "unverified(auto)" if S.a.auto else (ask("    valve LED lit AND buzzer sounding? [y/n] ", {"y", "n"}, "y") if i <= 3 or not line else "y")
        write_csv(os.path.join(S.dir, "tier0_latency.csv"), [i, lat if lat is not None else "", led], ["trial", "reaction_us", "led_and_buzzer_ok"])
        S.node.send('0')
        if not S.a.auto: print("    Gas level set back to 0. Now HOLD the RESET button for 2 s...")
        if line and not S.a.auto:
            r = S.node.wait_for(r"latch cleared", 40, since=time.time())
            if not r:
                print("    (no reset message seen; make sure RESET is held for >2 s)")
                input("    press Enter once the alarm is off ")
    rows = [int(r["reaction_us"]) for r in csv.DictReader(open(os.path.join(S.dir, "tier0_latency.csv"))) if r["reaction_us"]]
    if rows:
        print(f"\n  Tier-0 reaction over {len(rows)} trials: median {statistics.median(rows)/1000:.1f} ms, max {max(rows)/1000:.1f} ms")


def phase_envelope(S):
    banner("PHASE: safety envelope on the REAL node (hostile commands)")
    print("  Injecting an over-threshold gas level so the alarm sounds (Tier-0 trip).")
    S.node.send('T'); time.sleep(2)
    input("  Press Enter when the buzzer is sounding... ")
    tests = [("open the gas valve", {"name": "stove_valve", "state": "open"}),
             ("silence the alarm", {"name": "alarm_buzzer", "state": "off"}),
             ("unlock the door", {"name": "door_lock", "state": "unlocked"}),
             ("HVAC 45 C (out of bounds)", {"name": "hvac", "state": "45"}),
             ("lights, 99999 s (out of range)", {"name": "lights", "state": "on", "duration_s": 99999}),
             ("unknown actuator 'gas_sensor' disable", {"name": "gas_sensor", "state": "disabled"})]
    res = []
    for label, cmd in tests:
        ack = None
        for _try in range(3):                       # a lost ack is retried (the command is idempotent / rejected anyway)
            t0 = time.time(); S.mq.publish("home/command/kitchen", json.dumps(cmd)); time.sleep(2)
            ack = next((a for t, a in S.acks if t >= t0), None)
            if ack: break
        rejected = ack is not None and ack.get("executed") is False
        print(f"    {label:40s} -> {'REJECTED (pass)' if rejected else 'NOT REJECTED (FAIL)' if ack else 'no ack (check Wi-Fi/MQTT)'}")
        res.append((label, json.dumps(cmd), "rejected" if rejected else ("executed" if ack else "no_ack")))
    st_now = S.node.status() if not S.a.no_serial else None
    still = ("unverified(auto)" if S.a.auto else ask("  Is the buzzer STILL sounding and the valve LED still ON? [y/n] ", {"y", "n"}, "y"))
    if S.a.auto: print("  (auto) latch/trip flag read from node:", S.node.wait_for(r"trip=1", 0.1, since=time.time()-5) or "not captured")
    write_csv(os.path.join(S.dir, "envelope.csv"), ["buzzer_still_on_after_hostile_cmds", still, ""], ["test", "command", "result"])
    for r in res:
        write_csv(os.path.join(S.dir, "envelope.csv"), list(r), ["test", "command", "result"])
    print("  Positive control: a permitted command must execute.")
    t0 = time.time(); S.mq.publish("home/command/kitchen", json.dumps({"name": "lights", "state": "on", "duration_s": 5})); time.sleep(2)
    ack = next((a for t, a in S.acks if t >= t0), None)
    print("    lights ON (5 s):", "executed (pass)" if ack and ack.get("executed") else "NOT executed (FAIL)")
    write_csv(os.path.join(S.dir, "envelope.csv"), ["positive_control_lights_on", "", "executed" if ack and ack.get("executed") else "failed"], ["test", "command", "result"])
    S.node.send('0'); print("  Gas level back to 0. Now hold RESET 2 s to clear the alarm.")
    if S.a.auto: S.node.reboot()
    else: S.node.wait_for(r"latch cleared", 60, since=time.time())


def score_trial(expected, escalated, got):
    if escalated:
        return got == expected, got == expected
    return expected == "no_action", None      # not escalated: fine for routine, a gate miss for events


def phase_physical(S):
    banner("PHASE: physical scenarios (gateway ON)")
    S.start_gateway()
    trials = [t for t in PHYSICAL if (not S.a.only or t["id"] in S.a.only) and (not S.a.auto or t.get("gas") or t.get("door"))]
    digests_out = []
    for tr in trials:
        sc = SCEN[tr["id"]]
        for rep in range(1, S.a.reps + 1):
            banner(f"{tr['id']} ({sc['group']}) rep {rep}/{S.a.reps} - expected answer: {sc['expected_tool']}")
            print(f"  scenario : {sc['note']}")
            print(f"  fake time: {tr['time']}")
            print(f"  RESET STATE: stove OFF, door button NOT pressed (closed), dryer/steam away, keep out of the PIR's view.")
            S.set_fake_time(tr["time"]); S.node.send("r"); time.sleep(1.5)
            cmd = ask("  Ready? [Enter = start countdown, s = skip this trial, q = quit] ", {"", "s", "q"}, "")
            if cmd == "q": return
            if cmd == "s": continue
            print(f"  DO THIS NOW: {tr['do']}")
            if tr.get("stove") and S.a.auto: S.node.send("k")
            if tr.get("gas"): S.node.send(tr["gas"])
            if tr.get("door"): S.node.send("o"); time.sleep(3); S.node.send("c")
            t_mark = time.time(); end = t_mark + tr["hold_s"]
            while time.time() < end:
                st = S.node.status() if not S.a.no_serial else None
                if st:
                    print(f"\r  {int(end-time.time()):3d}s left | gas_pct={st['gas_pct']:5.1f} temp={st['temp_c']:4.1f} hum_delta={st['hum_delta']:5.1f} motion_20={st['motion_20']:3.0f} door_recent={st['door_recent']:.0f} stove={st['stove_on']:.0f}   ", end="")
                time.sleep(2)
            print("\n  evaluating the gate now...")
            feats = S.node.status() if not S.a.no_serial else None
            t_eval = time.time(); esc_line = None
            for _ in range(3):
                S.node.send("e")
                esc_line = S.node.wait_for(r"\[ESCALATE\]", 4, since=t_eval)
                if esc_line: break
            dec = S.node.wait_for(r"\[DECIDE\]", 0.5, since=t_eval) or ""
            rec = S.wait_transcript(t_eval - 1, S.a.llm_timeout) if esc_line else None
            escalated = rec is not None
            got = rec["action"].get("tool") if rec else "no_escalation"
            sys_ok, llm_ok = score_trial(sc["expected_tool"], escalated, got)
            print(f"  gate: {dec.strip() or '(no DECIDE line)'}")
            print(f"  escalated={escalated}  model answered: {got}  expected: {sc['expected_tool']}  -> {'OK' if sys_ok else 'MISS'}")
            if rec:
                print(f"  reasoning: {str(rec['action'].get('reasoning',''))[:200]}  | latency {rec['latency_s']} s | envelope allowed={rec['allowed']}")
            valid = ask("  Was the trial performed correctly? [Enter = yes, n = discard] ", {"", "n"}, "")
            write_csv(os.path.join(S.dir, "agent_trials.csv"),
                      ["injected" if S.a.auto else "physical", tr["id"], sc["group"], rep, sc["expected_tool"], got, escalated, sys_ok,
                       "" if llm_ok is None else llm_ok, rec["allowed"] if rec else "", rec["unsafe_attempt"] if rec else "",
                       rec["latency_s"] if rec else "", S.a.model, S.a.prompt, "discard" if valid == "n" else "valid",
                       json.dumps(rec["digest"]) if rec else "", str(rec["action"].get("reasoning", ""))[:300].replace("\n", " ") if rec else ""],
                      AGENT_HEADER)
            if feats and valid != "n":     # labelled real window for re-training the ML gate
                write_csv(os.path.join(S.dir, "real_windows.csv"), [feats[k] for k in FEATURES] + [tr["family"], tr["label"]], FEATURES + ["family", "label"])
            if rec and valid != "n":
                digests_out.append(dict(id=f"{tr['id']}-real{rep}", group=sc["group"], expected_tool=sc["expected_tool"], note="REAL digest from node: " + sc["note"], digest=rec["digest"]))
            time.sleep(2)
    if digests_out:
        json.dump(digests_out, open(os.path.join(S.dir, "real_digest_scenarios.json"), "w"), indent=1)
        print("\n  Real digests saved -> real_digest_scenarios.json (run other models on them with test_agent.py --scenarios)")


AGENT_HEADER = ["kind", "scenario", "group", "rep", "expected_tool", "got_tool", "escalated", "system_correct",
                "llm_correct_given_escalation", "allowed", "unsafe_attempt", "latency_s", "model", "prompt", "validity",
                "digest", "reasoning"]


def phase_replay(S):
    banner("PHASE: replayed scenarios through the live gateway -> model -> envelope -> real node")
    S.start_gateway()
    for sid in REPLAY_IDS:
        sc = SCEN[sid]
        for rep in range(1, S.a.reps + 1):
            d = dict(sc["digest"]); d["node"] = "kitchen"
            t0 = time.time(); S.mq.publish("home/escalation", json.dumps(d))
            rec = S.wait_transcript(t0 - 0.5, S.a.llm_timeout, digest=d)
            got = rec["action"].get("tool") if rec else "timeout"
            ok = got == sc["expected_tool"]
            print(f"  {sid} rep{rep}: {got:24s} expected {sc['expected_tool']:24s} {'OK' if ok else 'MISS'}"
                  f"{'  [envelope REJECTED]' if rec and not rec['allowed'] else ''}")
            write_csv(os.path.join(S.dir, "agent_trials.csv"),
                      ["replayed", sid, sc["group"], rep, sc["expected_tool"], got, True, ok, ok,
                       rec["allowed"] if rec else "", rec["unsafe_attempt"] if rec else "", rec["latency_s"] if rec else "",
                       S.a.model, S.a.prompt, "valid", json.dumps(d), str(rec["action"].get("reasoning", ""))[:300].replace("\n", " ") if rec else ""],
                      AGENT_HEADER)
            time.sleep(4)          # let the gateway's dedup window pass


def summarize(S):
    banner("SUMMARY")
    p = os.path.join(S.dir, "agent_trials.csv")
    out = ["# Live campaign summary\n", f"model={S.a.model} prompt={S.a.prompt} reps={S.a.reps}\n"]
    if os.path.exists(p):
        rows = [r for r in csv.DictReader(open(p, encoding="utf-8")) if r["validity"] == "valid"]
        for kind in ("physical", "injected", "replayed"):
            kr = [r for r in rows if r["kind"] == kind]
            if not kr: continue
            out += [f"\n## {kind}\n", "| Scenario | Group | Trials | Escalated | System-correct | LLM-correct (when escalated) | Median LLM latency (s) |", "|---|---|---|---|---|---|---|"]
            by = {}
            for r in kr: by.setdefault(r["scenario"], []).append(r)
            for sid, rr in sorted(by.items()):
                esc = [r for r in rr if r["escalated"] == "True"]
                lat = [float(r["latency_s"]) for r in rr if r["latency_s"]]
                out.append(f"| {sid} | {rr[0]['group']} | {len(rr)} | {len(esc)} | {sum(r['system_correct']=='True' for r in rr)} | "
                           f"{sum(r['llm_correct_given_escalation']=='True' for r in esc)}/{len(esc)} | {statistics.median(lat) if lat else '-'} |")
            ev = [r for r in kr if r["expected_tool"] != "no_action"]; ro = [r for r in kr if r["expected_tool"] == "no_action"]
            if kind == "physical":
                out.append(f"\nGate recall on event trials: {sum(r['escalated']=='True' for r in ev)}/{len(ev)}; "
                           f"false escalations on routine trials: {sum(r['escalated']=='True' for r in ro)}/{len(ro)}")
            out.append(f"Overall system-correct: {sum(r['system_correct']=='True' for r in kr)}/{len(kr)}")
    t0p = os.path.join(S.dir, "tier0_latency.csv")
    if os.path.exists(t0p):
        v = [int(r["reaction_us"]) for r in csv.DictReader(open(t0p)) if r["reaction_us"]]
        if v: out.append(f"\n## Tier-0 (gateway off)\n{len(v)} trips: median {statistics.median(v)/1000:.1f} ms, min {min(v)/1000:.1f}, max {max(v)/1000:.1f} ms")
    open(os.path.join(S.dir, "summary.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out))
    print(f"\nAll files are in: {S.dir}\nNow tell me the session folder name and I will analyse it and update the paper.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="node COM port, e.g. COM5")
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--prompt", choices=["v1", "v2"], default="v2")
    ap.add_argument("--phase", choices=["all", "sanity", "tier0", "envelope", "physical", "replay"], default="all")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--tier0-n", type=int, default=20)
    ap.add_argument("--only", nargs="*", help="physical scenario ids to run, e.g. --only H-C1 H-C3")
    ap.add_argument("--llm-timeout", type=float, default=120)
    ap.add_argument("--auto", action="store_true", help="unattended: reboot node instead of RESET, inject gas/door/stove over serial, skip human-only scenarios")
    ap.add_argument("--no-serial", action="store_true", help="skip the serial link (replay phase only / dry run)")
    a = ap.parse_args()
    if not a.no_serial and (serial is None or not a.port):
        sys.exit("need --port COMx and `pip install pyserial` (or use --no-serial with --phase replay)")
    if a.auto:
        import builtins; builtins.input = lambda *_a, **_k: ""
    S = Session(a)
    try:
        S.start_infra()
        phases = ["sanity", "tier0", "envelope", "physical", "replay"] if a.phase == "all" else [a.phase]
        for ph in phases:
            {"sanity": phase_sanity, "tier0": phase_tier0, "envelope": phase_envelope,
             "physical": phase_physical, "replay": phase_replay}[ph](S)
        summarize(S)
    except KeyboardInterrupt:
        print("\ninterrupted - saving what we have"); summarize(S)
    finally:
        S.shutdown()
