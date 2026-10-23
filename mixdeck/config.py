"""Mixdeck settings: one JSON file, written shortly after every change."""
import json
import os
import re
import tempfile

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "mixdeck")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Strip kinds
HW_IN, VIRT_IN, APP, HW_OUT, VIRT_OUT = "hw", "vi", "app", "ohw", "ovi"
INPUT_KINDS = (HW_IN, VIRT_IN)
OUTPUT_KINDS = (HW_OUT, VIRT_OUT)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "strip"


def default_config(default_sink=None, default_source=None):
    """First-run layout: mic, Apps and Chat in; speakers (A1) and a call mic (B1) out."""
    inputs = []
    if default_source:
        inputs.append({"id": "mic", "kind": HW_IN, "name": "Mic", "device": default_source,
                       "vol": 1.0, "mute": False, "solo": False, "pan": 0.0,
                       "routes": {"A1": False, "B1": True}})
    inputs += [
        {"id": "apps", "kind": VIRT_IN, "name": "Apps", "device": "mixdeck_apps",
         "vol": 1.0, "mute": False, "solo": False, "pan": 0.0, "routes": {"A1": True, "B1": False}},
        {"id": "chat", "kind": VIRT_IN, "name": "Chat", "device": "mixdeck_chat",
         "vol": 1.0, "mute": False, "solo": False, "pan": 0.0, "routes": {"A1": True, "B1": False}},
    ]
    outputs = []
    if default_sink:
        outputs.append({"id": "a1", "kind": HW_OUT, "bus": "A1", "name": "Speakers",
                        "device": default_sink, "vol": 1.0, "mute": False})
    outputs.append({"id": "b1", "kind": VIRT_OUT, "bus": "B1", "name": "Chat out",
                    "device": "mixdeck_chat_out", "vol": 1.0, "mute": False})
    return {
        "version": 1,
        "inputs": inputs,
        "outputs": outputs,
        "apps": {},              # app key -> {"target": strip id}
        "default_sink": "apps",  # input strip new apps play into
        "xtouch": {"enabled": True},
    }


def load():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        # Keep the broken file for inspection and start fresh
        bad = CONFIG_FILE + ".broken"
        try:
            os.replace(CONFIG_FILE, bad)
        except OSError:
            pass
        print(f"config unreadable ({e}); moved to {bad}", flush=True)
        return None


def _clean(obj):
    """Drop runtime-only keys (starting with "_") before saving."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def save(cfg):
    cfg = _clean(cfg)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def next_bus(cfg, kind):
    """A1..A5 for hardware outputs, B1..B3 for virtual ones."""
    letter = "A" if kind == HW_OUT else "B"
    used = {o["bus"] for o in cfg["outputs"]}
    for n in range(1, 10):
        if f"{letter}{n}" not in used:
            return f"{letter}{n}"
    return None


def unique_id(cfg, base):
    ids = {s["id"] for s in cfg["inputs"] + cfg["outputs"]}
    sid, n = slug(base), 2
    while sid in ids:
        sid, n = f"{slug(base)}{n}", n + 1
    return sid
