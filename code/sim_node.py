"""
sim_node.py — a VIRTUAL room node for testing the whole gateway loop with no hardware.

It publishes digests from scenarios.json to home/escalation exactly as home_node.ino
would, prints whatever the gateway commands back, and (like real firmware) enforces the
asymmetric grammar on received commands. Use it for step 2 of HARDWARE_SETUP.md and as
the "trace-driven on the real gateway" evaluation if hardware stalls.

  python sim_node.py --list
  python sim_node.py --scenario H-C1            # one scenario
  python sim_node.py --all --gap 5              # replay all 24, 5 s apart
  python sim_node.py --inject-unsafe            # send a hostile 'open valve' straight
                                                # at the node grammar (must be rejected)
"""
import argparse, json, os, time
import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = json.load(open(os.path.join(HERE, "laptop_agent", "scenarios.json"), encoding="utf-8"))

ap = argparse.ArgumentParser()
ap.add_argument("--broker", default="localhost")
ap.add_argument("--node", default="kitchen")
ap.add_argument("--scenario")
ap.add_argument("--all", action="store_true")
ap.add_argument("--gap", type=float, default=8)
ap.add_argument("--list", action="store_true")
ap.add_argument("--inject-unsafe", action="store_true")
a = ap.parse_args()

if a.list:
    for s in SCEN:
        print(s["id"], s["group"], "-", s["note"])
    raise SystemExit

# Node-side asymmetric grammar (mirror of onCommand() in home_node.ino)
def node_grammar(cmd):
    name, state = cmd.get("name"), str(cmd.get("state", ""))
    if name == "stove_valve" and state == "closed": return "VALVE CLOSED"
    if name == "alarm_buzzer" and state == "on": return "BUZZER ON"
    if name == "door_lock" and state == "locked": return "DOOR LOCKED"
    if name == "lights" and state in ("on", "off"): return f"LIGHTS {state.upper()}"
    if name == "hvac":
        try:
            if 16 <= float(state) <= 30: return f"HVAC SETPOINT {state}"
        except ValueError:
            pass
    return None


def on_message(c, _, m):
    cmd = json.loads(m.payload)
    if m.topic.startswith("home/command/"):
        res = node_grammar(cmd)
        print(f"  <- command {cmd}: " + (f"EXECUTED ({res})" if res else "REJECTED BY NODE GRAMMAR"))
        c.publish(f"home/ack/{a.node}", json.dumps({"cmd": cmd, "executed": bool(res)}))
    else:
        print(f"  <- {m.topic}: {cmd}")


try:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    c = mqtt.Client()
c.on_message = on_message
c.connect(a.broker, 1883)
c.subscribe(f"home/command/{a.node}"); c.subscribe("home/notify")
c.loop_start()

if a.inject_unsafe:
    for cmd in ({"name": "stove_valve", "state": "open"}, {"name": "alarm_buzzer", "state": "off"},
                {"name": "door_lock", "state": "unlocked"}, {"name": "hvac", "state": "45"}):
        print("hostile command:", cmd)
        on_message(c, None, type("M", (), {"topic": f"home/command/{a.node}",
                                            "payload": json.dumps(cmd)}))
    raise SystemExit

todo = SCEN if a.all else [s for s in SCEN if s["id"] == a.scenario]
if not todo:
    raise SystemExit("choose --scenario ID, --all or --list")
for s in todo:
    d = dict(s["digest"]); d["node"] = a.node
    print(f"\n{s['id']} ({s['group']}) expected={s['expected_tool']}: {s['note']}")
    c.publish("home/escalation", json.dumps(d))
    time.sleep(a.gap)
c.loop_stop()
