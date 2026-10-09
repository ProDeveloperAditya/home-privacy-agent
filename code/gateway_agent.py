"""
gateway_agent.py — the live Tier 1 daemon on the laptop (zero-egress). v2

  * subscribes to node escalations on the LOCAL MQTT broker (home/escalation)
  * asks the LOCAL model (Ollama on localhost) — nothing else is ever contacted
  * validates the proposal with the same envelope the nodes enforce, publishes commands
  * fail-SAFE: any error / bad JSON / timeout  ->  notify_resident, never an actuation
  * serves local time to nodes (home/time) so firmware needs no internet NTP
  * tracks node liveness via MQTT last-will (home/status/<node>) and notifies on loss
  * logs every decision (incl. the fields that would have egressed to a cloud) to
    transcripts.jsonl  — this file is your live-evaluation dataset.

Setup:  pip install paho-mqtt ; install mosquitto + Ollama ; ollama pull llama3.2:3b
Run:    python gateway_agent.py [--model llama3.2:3b] [--broker localhost]
"""
import argparse, json, os, queue, sys, threading, time, urllib.request
import paho.mqtt.client as mqtt

sys.stdout.reconfigure(line_buffering=True)     # see decisions immediately, even when piped to a file
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "laptop_agent"))
from test_agent import envelope_check, is_unsafe_attempt, egress_fields, PROMPT_V1, PROMPT_V2

ap = argparse.ArgumentParser()
ap.add_argument("--model", default="llama3.2:3b")
ap.add_argument("--broker", default="localhost")
ap.add_argument("--ollama", default="http://localhost:11434/v1/chat/completions")
ap.add_argument("--dedup-s", type=int, default=60, help="ignore identical reason from a node within N s")
ap.add_argument("--prompt", choices=["v1", "v2"], default="v2", help="system-prompt version (v2 = explicit decision procedure)")
ap.add_argument("--fake-time", help="HH:MM sent to nodes instead of the real clock (physical night-time trials; label as such in the paper)")
cfg = ap.parse_args()
SYSTEM_PROMPT = open(PROMPT_V2 if cfg.prompt == "v2" else PROMPT_V1, encoding="utf-8").read()

LOG = os.path.join(HERE, "transcripts.jsonl")
NOTIFY_LOG = os.path.join(HERE, "notifications.log")
work = queue.Queue()
last_seen = {}          # (node, reason) -> time


def ask_model(digest):
    body = {"model": cfg.model, "temperature": 0.2, "max_tokens": 300, "seed": 7,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": json.dumps(digest)}]}
    req = urllib.request.Request(cfg.ollama, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        content = json.load(r)["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    a = json.loads(content)
    if not isinstance(a, dict):
        raise ValueError("model output is not an object")
    return a


def deliberate(digest):
    """Two attempts, then fail-safe notify."""
    err = None
    for _ in range(2):
        try:
            return ask_model(digest), None
        except Exception as e:                       # noqa: BLE001 — any failure => fail-safe
            err = e
    return ({"tool": "notify_resident",
             "args": {"severity": "warning",
                      "message": f"Home agent could not decide ({err}). Please check the house."},
             "reasoning": "fail-safe"}, str(err))


def notify(client, args, node):
    line = f"{time.strftime('%F %T')} [{node}] {args.get('severity','info').upper()}: {args.get('message','')}"
    print("NOTIFY", line)
    open(NOTIFY_LOG, "a", encoding="utf-8").write(line + "\n")
    client.publish("home/notify", json.dumps(args))


def worker(client):
    while True:
        digest = work.get()
        node = digest.get("node", "unknown")
        t0 = time.time()
        action, err = deliberate(digest)
        ok, why = envelope_check(action)
        rec = {"t": time.time(), "model": cfg.model, "prompt": cfg.prompt, "digest": digest, "action": action,
               "allowed": ok, "reject_reason": why, "unsafe_attempt": is_unsafe_attempt(action),
               "model_error": err, "latency_s": round(time.time() - t0, 2),
               "egress_fields_if_cloud": egress_fields(digest)}
        open(LOG, "a", encoding="utf-8").write(json.dumps(rec) + "\n")
        print(f"[{node}] -> {action.get('tool')} "
              f"({'ok' if ok else 'REJECTED: ' + why}) {rec['latency_s']}s")
        tool, args = action.get("tool"), action.get("args", {})
        if not ok:                                   # rejected proposal -> tell a human
            notify(client, {"severity": "info",
                            "message": f"Agent proposal rejected by safety envelope: {why}"}, node)
        elif tool == "set_actuator":
            client.publish(f"home/command/{node}", json.dumps(args))
        elif tool == "notify_resident":
            notify(client, args, node)
        elif tool == "request_sensor_recheck":
            client.publish(f"home/command/{node}", json.dumps({"recheck": args.get("sensor")}))
        # log_observation / no_action: logged above, nothing else to do


def on_message(client, _, msg):
    try:
        payload = json.loads(msg.payload)
    except json.JSONDecodeError:
        return
    if msg.topic == "home/escalation":
        key = (payload.get("node"), payload.get("escalation_reason"))
        if time.time() - last_seen.get(key, 0) < cfg.dedup_s:
            return
        last_seen[key] = time.time()
        work.put(payload)
    elif msg.topic == "home/fake_time":              # campaign script sets/clears the fake clock
        cfg.fake_time = payload.get("time") or None
        print("fake time ->", cfg.fake_time)
        send_time(client)                            # apply immediately, not at the next 30 s beacon
    elif msg.topic.startswith("home/status/"):
        node = msg.topic.split("/")[-1]
        if payload.get("state") == "offline":
            notify(client, {"severity": "warning",
                            "message": f"Node '{node}' went offline — its hard-wired safety "
                                       "rules still run locally."}, node)
    elif msg.topic.startswith("home/ack/"):
        print("ACK", msg.topic, payload)


def send_time(client):
    lt = time.localtime()
    hour, minute = lt.tm_hour, lt.tm_min
    if cfg.fake_time:                                # test night/day scenarios at any hour
        hour, minute = map(int, cfg.fake_time.split(":"))
    client.publish("home/time", json.dumps({"epoch": int(time.time()), "hour": hour,
                                            "min": minute, "weekday": lt.tm_wday < 5}), retain=True)


def time_beacon(client):
    while True:
        send_time(client)
        time.sleep(30)


try:                                                 # paho-mqtt 2.x
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:                               # paho-mqtt 1.x
    c = mqtt.Client()
c.on_message = on_message
c.connect(cfg.broker, 1883)
for t in ("home/escalation", "home/status/+", "home/ack/+", "home/fake_time"):
    c.subscribe(t)
threading.Thread(target=worker, args=(c,), daemon=True).start()
threading.Thread(target=time_beacon, args=(c,), daemon=True).start()
print(f"gateway agent up — model={cfg.model}, prompt={cfg.prompt}, zero-egress, logging to {LOG}")
c.loop_forever()
