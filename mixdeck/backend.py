"""Qt side of Mixdeck: owns the settings, the audio engine, meters and X-Touch, and
exposes strips to QML as list models plus slots for every control."""
import math
import time

from PySide6.QtCore import (QAbstractListModel, QByteArray, QModelIndex, QObject, Qt, QTimer,
                            Property, Signal, Slot)

from . import config
from .audio import Engine, chan_mode, mono_node
from .config import APP, HW_IN, HW_OUT, INPUT_KINDS, OUTPUT_KINDS, VIRT_IN, VIRT_OUT
from .meters import Meters

# The X-Touch scribble strips can show these seven colours, so strips use the same set
PALETTE = {"red": "#f87171", "yellow": "#f5a524", "green": "#4ade80", "cyan": "#2dd4bf",
           "blue": "#60a5fa", "magenta": "#c084fc", "white": "#e5e7eb"}
KIND_INFO = {  # label, default colour
    HW_IN: ("Hardware", "yellow"),
    VIRT_IN: ("Virtual", "cyan"),
    APP: ("App", "magenta"),
    HW_OUT: ("Hardware", "white"),
    VIRT_OUT: ("Virtual", "blue"),
}
ROLES = ["sid", "kind", "kindLabel", "accent", "name", "device", "vol", "db", "mute", "solo",
         "hasSolo", "pan", "hasPan", "routes", "isApp", "target", "isOut", "bus", "xtTag",
         "missing", "isDefault", "mono", "hasMono", "colorName", "channel", "channelText",
         "channelOptions"]


def channel_options(chans):
    """Choices for an input strip's channel picker, from the device's channel names."""
    opts = [{"id": "stereo", "short": "STEREO", "label": "Stereo (all channels)"},
            {"id": "mono", "short": "MONO", "label": "Mono (mix to one)"}]
    if len(chans) > 1:
        for i, ch in enumerate(chans):
            side = " (left)" if ch == "front-left" else " (right)" if ch == "front-right" else ""
            opts.append({"id": ch, "short": f"IN {i + 1}", "label": f"Input {i + 1} only{side}"})
    return opts


def db_text(vol):
    if vol <= 0.0005:
        return "-inf"
    db = 60 * math.log10(vol)
    return f"{0.0 if abs(db) < 0.05 else db:.1f} dB"


def meter_pos(peak):
    """Linear peak -> 0..1 meter position over -60..0 dB."""
    if peak <= 0.001:
        return 0.0
    return max(0.0, min(1.0, (20 * math.log10(peak) + 60) / 60))


class StripModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def roleNames(self):
        return {Qt.UserRole + i: QByteArray(r.encode()) for i, r in enumerate(ROLES)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        return self._items[index.row()].get(ROLES[role - Qt.UserRole])

    def set_items(self, items):
        if [i["sid"] for i in items] != [i["sid"] for i in self._items]:
            self.beginResetModel()
            self._items = items
            self.endResetModel()
            return
        for row, (old, new) in enumerate(zip(self._items, items)):
            if old != new:
                changed = [Qt.UserRole + i for i, r in enumerate(ROLES) if old.get(r) != new.get(r)]
                self._items[row] = new
                ix = self.index(row)
                self.dataChanged.emit(ix, ix, changed)


class Backend(QObject):
    levelsChanged = Signal()
    xtChanged = Signal()
    targetsChanged = Signal()
    _invoke = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._invoke.connect(lambda fn: fn(), Qt.QueuedConnection)
        self.engine = Engine(on_event=lambda *_: self._invoke.emit(self.schedule_refresh))

        cfg = config.load()
        if cfg is None:
            sink, source = self.engine.defaults()
            cfg = config.default_config(sink, source)
        self.cfg = cfg
        self.apps_live = []
        self._seen_streams = set()
        self._set_at = {}  # strip id -> time we last changed it (ignore echoes)
        self._levels = {}
        self._targets = []
        self._window_visible = False
        self._missing = set()
        self._desc = {}
        self._chans = {}

        self.inputs = StripModel(self)
        self.apps = StripModel(self)
        self.outputs = StripModel(self)

        for s in self.cfg["inputs"] + self.cfg["outputs"]:
            self.engine.ensure_virtual(s)
        self.sync_channels()
        self.apply_all()
        self.engine.sync_routes(self.cfg)
        self.engine.set_default_sink(self.strip(self.cfg.get("default_sink")))
        self.save_now()

        self._refresh_timer = QTimer(self, singleShot=True, interval=60, timeout=self.refresh)
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self.save_now)
        self._level_timer = QTimer(self, interval=33, timeout=self._tick_levels)
        self._level_timer.start()
        self._heal_timer = QTimer(self, interval=5000, timeout=self._heal)
        self._heal_timer.start()

        self.meters = Meters()
        self.xt = None
        if self.cfg.get("xtouch", {}).get("enabled", True):
            try:
                from .xtouch import XTouch
                self.xt = XTouch(self)
                self.xt.start()
            except Exception as e:
                print(f"X-Touch support off: {e}", flush=True)
        self._surface = ([], None)
        self.refresh()

    # ------------------------------------------------------------- lookup

    def strip(self, sid):
        for s in self.cfg["inputs"] + self.cfg["outputs"]:
            if s["id"] == sid:
                return s
        return None

    def app(self, sid):
        for a in self.apps_live:
            if f"app:{a['index']}" == sid:
                return a
        return None

    def color_name(self, s):
        """Colour name for a device strip or a live app dict."""
        if "index" in s:  # app
            name = self.cfg["apps"].get(s["key"], {}).get("color")
            return name if name in PALETTE else KIND_INFO[APP][1]
        name = s.get("color")
        return name if name in PALETTE else KIND_INFO[s["kind"]][1]

    def solo_active(self):
        return any(s.get("solo") for s in self.cfg["inputs"])

    def master(self):
        return next((o for o in self.cfg["outputs"] if o["kind"] == HW_OUT), None)

    # ------------------------------------------------------------ syncing

    def apply_all(self):
        solo = self.solo_active()
        for s in self.cfg["inputs"] + self.cfg["outputs"]:
            self.engine.apply(s, solo)

    def sync_channels(self):
        solo = self.solo_active()
        for s in self.engine.sync_mono(self.cfg):
            self.engine.apply(s, solo)

    def schedule_refresh(self):
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def schedule_save(self):
        self._save_timer.start()

    def save_now(self):
        try:
            config.save(self.cfg)
        except OSError as e:
            print(f"couldn't save settings: {e}", flush=True)

    def _heal(self):
        """Recreate missing virtual devices and links (e.g. after PipeWire restarts)."""
        for s in self.cfg["inputs"] + self.cfg["outputs"]:
            self.engine.ensure_virtual(s)
        self.sync_channels()
        self.engine.sync_routes(self.cfg)

    def refresh(self):
        now = time.monotonic()
        solo = self.solo_active()
        self._missing = set()
        for s in self.cfg["inputs"] + self.cfg["outputs"]:
            r = self.engine.read(s)
            if r is None:
                self._missing.add(s["id"])
                continue
            vol, mute, desc, chans = r
            self._desc[s["id"]] = desc
            self._chans[s["id"]] = chans
            if now - self._set_at.get(s["id"], 0) < 1.0:
                continue
            changed = False
            if abs(vol - s["vol"]) > 0.003:
                s["vol"], changed = vol, True  # changed elsewhere, e.g. the panel volume applet
            if not solo and mute != s["mute"]:
                s["mute"], changed = mute, True
            if changed:
                self.schedule_save()

        order = {k: i for i, k in enumerate(self.cfg.get("app_order", []))}
        self.apps_live = sorted(self.engine.apps(), key=lambda a: (order.get(a["key"], len(order)), a["index"]))
        for a in self.apps_live:
            if a["index"] in self._seen_streams:
                continue
            self._seen_streams.add(a["index"])
            want = self.cfg["apps"].get(a["key"], {}).get("target")
            dest = self.strip(want)
            if dest and dest["device"] != a["sink"]:
                self.engine.move_app(a["index"], dest)
                a["sink"] = dest["device"]
        live = {a["index"] for a in self.apps_live}
        self._seen_streams &= live
        self._publish()

    # ---------------------------------------------------------- publishing

    def _xt_numbers(self):
        """Strip id -> label of the X-Touch fader it's on ("1".."8", "M")."""
        strips, master = self._surface
        out = {}
        bank = self.xt.bank if self.xt else 0
        for i, s in enumerate(strips[bank:bank + 8]):
            out[s["id"]] = str(i + 1)
        if master:
            out[master["id"]] = "M"
        return out

    def _device_item(self, s, xtn):
        label = KIND_INFO[s["kind"]][0]
        cname = self.color_name(s)
        is_in = s["kind"] in INPUT_KINDS
        mode = chan_mode(s) if is_in else "stereo"
        mono = mode != "stereo"
        opts = channel_options(self._chans.get(s["id"], [])) if is_in else []
        return {
            "channel": mode, "channelOptions": opts,
            "channelText": next((o["short"] for o in opts if o["id"] == mode), "STEREO"),
            "sid": s["id"], "kind": s["kind"], "kindLabel": label, "accent": PALETTE[cname],
            "colorName": cname, "mono": mono, "hasMono": is_in,
            "name": s["name"],
            "device": "Not connected" if s["id"] in self._missing else
                      ("Virtual" if s["kind"] in (VIRT_IN, VIRT_OUT) else self._desc.get(s["id"], s["device"])),
            "vol": s["vol"], "db": db_text(s["vol"]), "mute": s["mute"],
            "solo": bool(s.get("solo")), "hasSolo": is_in,
            "pan": s.get("pan", 0.0), "hasPan": is_in and not mono,
            "routes": [{"bus": o["bus"], "on": bool(s.get("routes", {}).get(o["bus"]))}
                       for o in self.cfg["outputs"]] if is_in else [],
            "isApp": False, "target": "", "isOut": not is_in, "bus": s.get("bus", ""),
            "xtTag": xtn.get(s["id"], ""), "missing": s["id"] in self._missing,
            "isDefault": self.cfg.get("default_sink") == s["id"],
        }

    def _app_item(self, a, xtn, by_device):
        sid = f"app:{a['index']}"
        cname = self.color_name(a)
        target = by_device.get(a["sink"])
        return {
            "sid": sid, "kind": APP, "kindLabel": KIND_INFO[APP][0], "accent": PALETTE[cname],
            "colorName": cname, "mono": False, "hasMono": False, "name": a["name"],
            "channel": "", "channelText": "", "channelOptions": [],
            "device": "Playing to " + (target["name"] if target else "another device"),
            "vol": a["vol"], "db": db_text(a["vol"]), "mute": a["mute"], "solo": False,
            "hasSolo": False, "pan": 0.0, "hasPan": False, "routes": [], "isApp": True,
            "target": target["id"] if target else "", "isOut": False, "bus": "",
            "xtTag": xtn.get(sid, ""), "missing": False, "isDefault": False,
        }

    def _publish(self):
        by_device = {s["device"]: s for s in self.cfg["inputs"] + self.cfg["outputs"]}
        master = self.master()
        surface = []
        for s in self.cfg["inputs"]:
            surface.append({"id": s["id"], "kind": s["kind"], "name": s["name"], "vol": s["vol"],
                            "color": self.color_name(s),
                            "mute": s["mute"], "solo": bool(s.get("solo")),
                            "pan": None if chan_mode(s) != "stereo" else s.get("pan", 0.0),
                            "a1": bool(s.get("routes", {}).get("A1"))})
        for a in self.apps_live:
            surface.append({"id": f"app:{a['index']}", "kind": APP, "name": a["name"],
                            "color": self.color_name(a),
                            "vol": a["vol"], "mute": a["mute"], "pan": None})
        for o in self.cfg["outputs"]:
            if o is not master:
                surface.append({"id": o["id"], "kind": o["kind"], "name": o["name"], "vol": o["vol"],
                                "color": self.color_name(o),
                                "mute": o["mute"], "pan": None})
        msnap = {"id": master["id"], "vol": master["vol"]} if master else None
        self._surface = (surface, msnap)

        xtn = self._xt_numbers()
        self.inputs.set_items([self._device_item(s, xtn) for s in self.cfg["inputs"]])
        self.apps.set_items([self._app_item(a, xtn, by_device) for a in self.apps_live])
        self.outputs.set_items([self._device_item(s, xtn) for s in self.cfg["outputs"]])

        targets = [{"id": s["id"], "name": s["name"]} for s in self.cfg["inputs"] if s["kind"] == VIRT_IN]
        targets += [{"id": s["id"], "name": s["name"]} for s in self.cfg["outputs"] if s["kind"] == HW_OUT]
        if targets != self._targets:
            self._targets = targets
            self.targetsChanged.emit()
        self._update_meters()
        self.xtChanged.emit()

    def _update_meters(self):
        if not (self._window_visible or (self.xt and self.xt.active)):
            self.meters.set_targets({})
            return
        t = {}
        for s in self.cfg["inputs"] + self.cfg["outputs"]:
            if s["id"] in self._missing:
                continue
            if s["kind"] in INPUT_KINDS and chan_mode(s) != "stereo":
                t[s["id"]] = (mono_node(s), None)
                continue
            monitor = s["kind"] in (VIRT_IN, HW_OUT)
            t[s["id"]] = (s["device"] + ".monitor" if monitor else s["device"], None)
        for a in self.apps_live:
            if a["sink"]:
                t[f"app:{a['index']}"] = (a["sink"] + ".monitor", a["index"])
        self.meters.set_targets(t)

    def _tick_levels(self):
        raw = self.meters.levels
        out = {}
        for sid, (l, r) in list(raw.items()):
            prev = self._levels.get(sid, [0.0, 0.0])
            new = [max(meter_pos(l), prev[0] - 0.025), max(meter_pos(r), prev[1] - 0.025)]
            out[sid] = new
        changed = out != self._levels
        self._levels = out
        # hand peaks to the X-Touch snapshot
        strips, master = self._surface
        for s in strips:
            l, r = raw.get(s["id"], (0.0, 0.0))
            s["peak"] = max(l, r)
        if changed:
            self.levelsChanged.emit()

    # -------------------------------------------------------- X-Touch hooks
    # (called on the X-Touch thread: only read snapshots or queue work)

    def surface(self):
        return self._surface

    def xt_changed(self):
        self._invoke.emit(self._publish)

    def xt_action(self, action, sid):
        if action == "mute":
            self._invoke.emit(lambda: self.toggleMute(sid))
        elif action == "solo":
            self._invoke.emit(lambda: self.toggleSolo(sid))
        elif action == "a1":
            self._invoke.emit(lambda: self.toggleRoute(sid, "A1"))

    def xt_volume(self, sid, vol):
        self._invoke.emit(lambda: self.setVolume(sid, vol))

    def xt_pan(self, sid, delta):
        def go():
            s = self.strip(sid)
            if s:
                self.setPan(sid, max(-1.0, min(1.0, s.get("pan", 0.0) + delta)))
        self._invoke.emit(go)

    # ------------------------------------------------------------ QML API

    def _get_inputs(self):
        return self.inputs

    def _get_apps(self):
        return self.apps

    def _get_outputs(self):
        return self.outputs

    inputsModel = Property(QObject, _get_inputs, constant=True)
    appsModel = Property(QObject, _get_apps, constant=True)
    outputsModel = Property(QObject, _get_outputs, constant=True)

    @Property("QVariantMap", notify=levelsChanged)
    def levels(self):
        return self._levels

    @Property("QVariantList", notify=targetsChanged)
    def targets(self):
        return self._targets

    @Property(bool, notify=xtChanged)
    def xtPresent(self):
        return bool(self.xt and self.xt.present)

    @Property(bool, notify=xtChanged)
    def xtActive(self):
        return bool(self.xt and self.xt.active)

    @Property(int, notify=xtChanged)
    def xtBank(self):
        return (self.xt.bank // 8 + 1) if self.xt else 1

    @Property("QVariantList", notify=xtChanged)
    def xtCells(self):
        strips, master = self._surface
        bank = self.xt.bank if self.xt else 0
        cells = []
        for i in range(8):
            s = strips[bank + i] if bank + i < len(strips) else None
            cells.append({"num": f"F{i + 1}", "name": (("MUTE" if s["mute"] else s["name"]) if s else "")[:7],
                          "color": PALETTE.get(s.get("color"), "#e5e7eb") if s else "#252b37",
                          "db": db_text(s["vol"]).replace(" dB", "") if s else "",
                          "vol": s["vol"] if s else 0.0})
        m = self.master()
        cells.append({"num": "MASTER", "name": (m["name"] if m else "")[:7],
                      "color": PALETTE[self.color_name(m)] if m else "#252b37",
                      "db": db_text(m["vol"]).replace(" dB", "") if m else "",
                      "vol": m["vol"] if m else 0.0})
        return cells

    @Slot(bool)
    def setXtMode(self, pc):
        if self.xt:
            self.xt.request_mode(pc)

    @Slot(int)
    def bankBy(self, step):
        if self.xt:
            strips, _ = self._surface
            self.xt.bank = max(0, min(self.xt.bank + step, max(0, len(strips) - 1)))
            self.xt.shown = {k: v for k, v in self.xt.shown.items() if k == "user"}
            self._publish()

    @Slot(bool)
    def setWindowVisible(self, visible):
        self._window_visible = visible
        self._update_meters()

    def _touch(self, sid):
        self._set_at[sid] = time.monotonic()

    @Slot(str, float)
    def setVolume(self, sid, vol):
        vol = max(0.0, min(1.0, vol))
        if sid.startswith("app:"):
            a = self.app(sid)
            if a:
                self.engine.set_app_volume(a["index"], vol)
                a["vol"] = vol
        else:
            s = self.strip(sid)
            if not s:
                return
            s["vol"] = vol
            self._touch(sid)
            self.engine.apply(s, self.solo_active())
            self.schedule_save()
        self._publish()

    @Slot(str)
    def toggleMute(self, sid):
        if sid.startswith("app:"):
            a = self.app(sid)
            if a:
                a["mute"] = not a["mute"]
                self.engine.set_app_mute(a["index"], a["mute"])
        else:
            s = self.strip(sid)
            if not s:
                return
            s["mute"] = not s["mute"]
            self._touch(sid)
            self.engine.apply(s, self.solo_active())
            self.schedule_save()
        self._publish()

    @Slot(str)
    def toggleSolo(self, sid):
        s = self.strip(sid)
        if not s or s["kind"] not in INPUT_KINDS:
            return
        s["solo"] = not s.get("solo")
        for x in self.cfg["inputs"]:
            self._touch(x["id"])
        self.apply_all()
        self.schedule_save()
        self._publish()

    @Slot(str, float)
    def setPan(self, sid, pan):
        s = self.strip(sid)
        if not s:
            return
        s["pan"] = round(max(-1.0, min(1.0, pan)), 2)
        self._touch(sid)
        self.engine.apply(s, self.solo_active())
        self.schedule_save()
        self._publish()

    @Slot(str, str)
    def toggleRoute(self, sid, bus):
        s = self.strip(sid)
        if not s or s["kind"] not in INPUT_KINDS:
            return
        routes = s.setdefault("routes", {})
        routes[bus] = not routes.get(bus, False)
        self.engine.sync_routes(self.cfg)
        self.schedule_save()
        self._publish()

    @Slot(str, str)
    def setChannel(self, sid, mode):
        s = self.strip(sid)
        if not s or s["kind"] not in INPUT_KINDS:
            return
        s["channel"] = mode or "stereo"
        s.pop("mono", None)
        self._touch(sid)
        self.sync_channels()
        self.engine.apply(s, self.solo_active())
        self.engine.sync_routes(self.cfg)
        self.schedule_save()
        self._publish()

    @Slot(str, int, int)
    def moveStrip(self, section, frm, to):
        """Drag-and-drop reorder within Inputs, Apps or Outputs. The order is also the
        X-Touch fader order; the leftmost hardware output is the master fader."""
        if frm == to:
            return
        if section == "apps":
            keys = []
            for a in self.apps_live:
                if a["key"] not in keys:
                    keys.append(a["key"])
            if not (0 <= frm < len(self.apps_live) and 0 <= to < len(self.apps_live)):
                return
            moving = self.apps_live.pop(frm)
            self.apps_live.insert(to, moving)
            seen = []
            for a in self.apps_live:
                if a["key"] not in seen:
                    seen.append(a["key"])
            rest = [k for k in self.cfg.get("app_order", []) if k not in seen]
            self.cfg["app_order"] = seen + rest
        else:
            lst = self.cfg.get(section)
            if lst is None or not (0 <= frm < len(lst) and 0 <= to < len(lst)):
                return
            lst.insert(to, lst.pop(frm))
        self.schedule_save()
        self._publish()

    @Slot(str, str)
    def setColor(self, sid, name):
        if name not in PALETTE:
            return
        if sid.startswith("app:"):
            a = self.app(sid)
            if not a:
                return
            self.cfg["apps"].setdefault(a["key"], {})["color"] = name
        else:
            s = self.strip(sid)
            if not s:
                return
            s["color"] = name
        self.schedule_save()
        self._publish()

    @Property("QVariantList", constant=True)
    def colors(self):
        return [{"name": n, "hex": h} for n, h in PALETTE.items()]

    @Slot(str, str)
    def setTarget(self, sid, target_id):
        a = self.app(sid)
        dest = self.strip(target_id)
        if not a or not dest:
            return
        self.engine.move_app(a["index"], dest)
        a["sink"] = dest["device"]
        self.cfg["apps"][a["key"]] = {"target": target_id}
        self.schedule_save()
        self._publish()

    @Slot(str)
    def setDefault(self, sid):
        s = self.strip(sid)
        if s and s["kind"] == VIRT_IN:
            self.cfg["default_sink"] = sid
            self.engine.set_default_sink(s)
            self.schedule_save()
            self._publish()

    @Slot(str, result="QVariantList")
    def hardwareChoices(self, kind):
        """Devices that can be added. Inputs can be added more than once (one strip per
        input of an audio interface); outputs only once."""
        ins, outs = self.engine.hardware()
        used = {s["device"] for s in self.cfg["inputs"] + self.cfg["outputs"]}
        out = []
        if kind == HW_IN:
            for dev, name, chans in ins:
                out.append({"device": dev, "name": name, "channel": "stereo", "label": "Stereo"})
                if len(chans) > 1:
                    for i, ch in enumerate(chans):
                        out.append({"device": dev, "name": name, "channel": ch, "label": f"Input {i + 1}"})
        else:
            out = [{"device": d, "name": n, "channel": "", "label": ""} for d, n in outs if d not in used]
        return out

    @Slot(str, str, str, str)
    def addStrip(self, kind, device, name, channel=""):
        name = (name or "").strip() or ("Virtual" if kind in (VIRT_IN, VIRT_OUT) else "Device")
        sid = config.unique_id(self.cfg, name)
        if kind in (VIRT_IN, VIRT_OUT):
            device = "mixdeck_" + sid
        if not device:
            return
        if kind in INPUT_KINDS:
            s = {"id": sid, "kind": kind, "name": name, "device": device, "vol": 1.0, "mute": False,
                 "solo": False, "pan": 0.0, "channel": channel or "stereo",
                 "routes": {o["bus"]: False for o in self.cfg["outputs"]}}
            self.cfg["inputs"].append(s)
        else:
            bus = config.next_bus(self.cfg, kind)
            if not bus:
                return
            s = {"id": sid, "kind": kind, "bus": bus, "name": name, "device": device,
                 "vol": 1.0, "mute": False}
            self.cfg["outputs"].append(s)
            for i in self.cfg["inputs"]:
                i.setdefault("routes", {})[bus] = False
        self.engine.ensure_virtual(s)
        self.sync_channels()
        self.engine.apply(s, self.solo_active())
        self.save_now()
        self.refresh()

    @Slot(str)
    def removeStrip(self, sid):
        s = self.strip(sid)
        if not s:
            return
        if s["kind"] in OUTPUT_KINDS:
            for i in self.cfg["inputs"]:
                i.get("routes", {})[s["bus"]] = False
        else:
            s["routes"] = {k: False for k in s.get("routes", {})}
            s["channel"], s["mono"] = "stereo", False
            self.engine.sync_mono(self.cfg)
        self.engine.sync_routes(self.cfg)
        if s["kind"] in OUTPUT_KINDS:
            self.cfg["outputs"].remove(s)
            for i in self.cfg["inputs"]:
                i.get("routes", {}).pop(s["bus"], None)
        else:
            self.cfg["inputs"].remove(s)
        if self.cfg.get("default_sink") == sid:
            self.cfg["default_sink"] = None
        self.engine.remove_virtual(s)
        self.save_now()
        self.refresh()

    @Slot(str, str)
    def renameStrip(self, sid, name):
        s = self.strip(sid)
        name = name.strip()
        if s and name:
            s["name"] = name
            self.save_now()
            self._publish()

    def shutdown(self):
        self._save_timer.stop()
        self.save_now()
        if self.xt:
            self.xt.shutdown()
            self.xt.join(timeout=2)
        self.meters.set_targets({})
        self.engine.close()
