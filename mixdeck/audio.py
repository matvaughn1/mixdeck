"""PipeWire side of Mixdeck: virtual devices, routing links, volumes, mutes and app streams.

Uses pulsectl (through pipewire-pulse) for volumes, mutes and moving app streams, and
pw-cli / pw-link for creating virtual devices and linking ports. Everything here runs on
the caller's thread; pulse events arrive on a background thread via `on_event`.
"""
import re
import subprocess
import threading
import time

import pulsectl

from .config import APP, HW_IN, HW_OUT, INPUT_KINDS, OUTPUT_KINDS, VIRT_IN, VIRT_OUT

METER_CLIENT = "Mixdeck meters"

# Streams that aren't really apps: our meters, PulseMeeter's plumbing, volume-change blips
SKIP_STREAM = re.compile(r"_peak|pm_route_|peak detect|mixdeck", re.I)


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def app_key(proplist):
    return (proplist.get("application.process.binary")
            or proplist.get("application.name")
            or proplist.get("media.name") or "app")


def mono_node(strip):
    """Name of the single-channel copy used when a strip isn't in stereo."""
    return f"mixdeck_mono_{strip['id']}"


def chan_mode(strip):
    """'stereo', 'mono' (L+R mixed) or one pulse channel name such as 'front-left'."""
    return strip.get("channel") or ("mono" if strip.get("mono") else "stereo")


def is_device_sink(kind):
    """True if the strip's PipeWire node is a sink (else a source)."""
    return kind in (VIRT_IN, HW_OUT)


class Engine:
    def __init__(self, on_event=None):
        self.pulse = pulsectl.Pulse("Mixdeck")
        self.on_event = on_event
        self._stop = False
        if on_event:
            threading.Thread(target=self._events, daemon=True, name="pulse-events").start()

    # ------------------------------------------------------------ helpers

    def _call(self, fn, *args):
        """Run a pulse call, reconnecting once if pipewire-pulse restarted."""
        try:
            return fn(self.pulse, *args)
        except (pulsectl.PulseDisconnected, pulsectl.PulseOperationFailed, OSError):
            try:
                self.pulse.close()
            except Exception:
                pass
            self.pulse = pulsectl.Pulse("Mixdeck")
            return fn(self.pulse, *args)

    def node(self, strip):
        """The pulse sink/source object for a device strip, or None if it's not there."""
        try:
            if is_device_sink(strip["kind"]):
                return self._call(lambda p: p.get_sink_by_name(strip["device"]))
            return self._call(lambda p: p.get_source_by_name(strip["device"]))
        except pulsectl.PulseIndexError:
            return None

    def level_node(self, strip):
        """Where a strip's volume and mute live: its own single-channel copy when it
        isn't stereo (so two strips on one interface don't share a fader), else the device."""
        if strip["kind"] in INPUT_KINDS and chan_mode(strip) != "stereo":
            try:
                return self._call(lambda p: p.get_source_by_name(mono_node(strip)))
            except pulsectl.PulseIndexError:
                return None
        return self.node(strip)

    def defaults(self):
        info = self._call(lambda p: p.server_info())
        return info.default_sink_name, info.default_source_name

    def hardware(self):
        """(inputs, outputs): (name, description, channel names) / (name, description)."""
        sinks = self._call(lambda p: p.sink_list())
        sources = self._call(lambda p: p.source_list())
        outs = [(s.name, s.description) for s in sinks if s.name.startswith(("alsa_", "bluez_"))]
        ins = [(s.name, s.description, list(s.channel_list)) for s in sources
               if s.name.startswith(("alsa_", "bluez_")) and not s.name.endswith(".monitor")]
        return ins, outs

    # ---------------------------------------------------- virtual devices

    def ensure_virtual(self, strip):
        """Create the null-sink node behind a virtual input/output if it's missing."""
        if strip["kind"] not in (VIRT_IN, VIRT_OUT) or self.node(strip) is not None:
            return
        media_class = "Audio/Sink" if strip["kind"] == VIRT_IN else "Audio/Source/Virtual"
        desc = strip["name"].replace('"', "'")
        props = (f'{{ factory.name=support.null-audio-sink node.name="{strip["device"]}" '
                 f'node.description="{desc}" media.class={media_class} '
                 f'audio.position="FL FR" monitor.channel-volumes=true object.linger=true }}')
        # pw-cli often prints harmless "no global" errors as it exits, so judge by
        # whether the device shows up rather than by its output
        r = run("pw-cli", "create-node", "adapter", props)
        for _ in range(40):  # wait for pipewire-pulse to see it
            if self.node(strip) is not None:
                return
            time.sleep(0.05)
        print(f"could not create {strip['device']}: {r.stderr.strip()}", flush=True)

    def remove_virtual(self, strip):
        if strip["kind"] in (VIRT_IN, VIRT_OUT):
            run("pw-cli", "destroy", strip["device"])

    # ------------------------------------------------------------ routing

    @staticmethod
    def _ports(flag):
        """{node name: {channel: full port name}} for output (-o) or input (-i) ports."""
        out = {}
        for line in run("pw-link", flag).stdout.splitlines():
            node, _, port = line.strip().rpartition(":")
            if node:
                out.setdefault(node, {})[port] = line.strip()
        return out

    @staticmethod
    def _channel(port):
        return port.rsplit("_", 1)[-1].upper()

    def _src_ports(self, outs, strip):
        prefix = "monitor_" if strip["kind"] == VIRT_IN else "capture_"
        return {self._channel(p): full for p, full in outs.get(strip["device"], {}).items()
                if p.startswith(prefix)}

    def _dst_ports(self, ins, out):
        prefix = "playback_" if out["kind"] == HW_OUT else "input_"
        return {self._channel(p): full for p, full in ins.get(out["device"], {}).items()
                if p.startswith(prefix)}

    @staticmethod
    def _pairs(src, dst):
        """Match ports by channel; a mono side feeds / is fed by every channel."""
        if not src or not dst:
            return []
        if len(src) == 1:
            s = next(iter(src.values()))
            return [(s, d) for d in dst.values()]
        if len(dst) == 1:
            d = next(iter(dst.values()))
            return [(s, d) for s in src.values()]
        return [(src[ch], dst[ch]) for ch in src if ch in dst]

    @staticmethod
    def _links():
        links, cur = set(), None
        for line in run("pw-link", "-l").stdout.splitlines():
            if not line.startswith(" "):
                cur = line.strip()
            elif "|->" in line and cur:
                links.add((cur, line.split("|->", 1)[1].strip()))
        return links

    def sync_routes(self, cfg):
        """Make the links between input and output strips match their A/B buttons.
        A strip in mono is routed from its mono copy instead (see sync_mono)."""
        outs, ins, links = self._ports("-o"), self._ports("-i"), self._links()
        for strip in cfg["inputs"]:
            stereo = self._src_ports(outs, strip)
            mono = {"MONO": p for p in outs.get(mono_node(strip), {}).values()}
            single = chan_mode(strip) != "stereo"
            active, inactive = (mono, stereo) if single and mono else (stereo, mono)
            for out in cfg["outputs"]:
                dst = self._dst_ports(ins, out)
                want = strip.get("routes", {}).get(out["bus"], False)
                for s, d in self._pairs(active, dst):
                    if want and (s, d) not in links:
                        run("pw-link", s, d)
                    elif not want and (s, d) in links:
                        run("pw-link", "-d", s, d)
                for s, d in self._pairs(inactive, dst):
                    if (s, d) in links:
                        run("pw-link", "-d", s, d)

    # --------------------------------------------------------------- mono

    @staticmethod
    def _mono_modules():
        """{node name: (pulse module index, its arguments)} for the copies we've loaded."""
        out = {}
        for line in run("pactl", "list", "short", "modules").stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[1] == "module-remap-source":
                m = re.search(r"source_name=(mixdeck_mono_\S+)", parts[2])
                if m:
                    out[m.group(1)] = (parts[0], parts[2].strip())
        return out

    def sync_mono(self, cfg):
        """Give every input strip that isn't stereo a single-channel copy of its device:
        'mono' mixes L+R (PipeWire averages them), a channel name picks just that channel
        (one input of an audio interface). Copies no longer wanted are unloaded.
        Returns the strips whose copy was just created (their volume needs setting)."""
        loaded = self._mono_modules()
        wanted = {}
        for strip in cfg["inputs"]:
            mode = chan_mode(strip)
            if mode == "stereo" or self.node(strip) is None:
                continue
            master = strip["device"] + ".monitor" if strip["kind"] == VIRT_IN else strip["device"]
            args = [f"source_name={mono_node(strip)}", f"master={master}", "channels=1", "channel_map=mono"]
            if mode != "mono":
                args += [f"master_channel_map={mode}", "remix=no"]
            wanted[mono_node(strip)] = (strip, args)
        for name, (idx, have) in loaded.items():
            if name not in wanted or have != " ".join(wanted[name][1]):
                run("pactl", "unload-module", idx)
        created = []
        for name, (strip, args) in wanted.items():
            if name in loaded and loaded[name][1] == " ".join(args):
                continue
            run("pactl", "load-module", "module-remap-source", *args)
            for _ in range(20):  # wait for its port so routing can use it
                if f"{name}:" in run("pw-link", "-o").stdout:
                    break
                time.sleep(0.05)
            created.append(strip)
        return created

    # ---------------------------------------------------- volume and mute

    def apply(self, strip, solo_active=False):
        """Push a device strip's volume, pan and mute to PipeWire."""
        obj = self.level_node(strip)
        if obj is None:
            return
        vol = max(0.0, min(1.5, strip["vol"]))
        n = len(obj.volume.values)
        pan = strip.get("pan", 0.0)
        if n == 2 and pan:
            values = [vol * min(1.0, 1.0 - pan), vol * min(1.0, 1.0 + pan)]
        else:
            values = [vol] * n
        mute = strip["mute"] or (solo_active and strip["kind"] in INPUT_KINDS and not strip.get("solo"))
        self._call(lambda p: p.volume_set(obj, pulsectl.PulseVolumeInfo(values)))
        if bool(obj.mute) != mute:
            self._call(lambda p: p.mute(obj, mute))

    def read(self, strip):
        """(volume, muted, description, channel names) as PipeWire has them, or None."""
        dev = self.node(strip)
        obj = self.level_node(strip)
        if dev is None or obj is None:
            return None
        return max(obj.volume.values or [0.0]), bool(obj.mute), dev.description, list(dev.channel_list)

    def set_default_sink(self, strip):
        if strip and self.node(strip) is not None:
            self._call(lambda p: p.sink_default_set(strip["device"]))

    # --------------------------------------------------------------- apps

    def apps(self):
        """Playing app streams: dicts with index, key, name, vol, mute, sink (name)."""
        sinks = {s.index: s.name for s in self._call(lambda p: p.sink_list())}
        out = []
        for si in self._call(lambda p: p.sink_input_list()):
            pl = si.proplist
            ident = " ".join(pl.get(k, "") for k in ("application.name", "node.name", "media.name"))
            if SKIP_STREAM.search(ident) or pl.get("media.role") == "event" \
                    or pl.get("application.id") == "org.PulseAudio.pavucontrol":
                continue
            out.append({
                "index": si.index,
                "key": app_key(pl),
                "name": pl.get("application.name") or pl.get("media.name") or "App",
                "icon": pl.get("application.icon_name", ""),
                "vol": max(si.volume.values or [0.0]),
                "mute": bool(si.mute),
                "sink": sinks.get(si.sink, ""),
                "sink_index": si.sink,
            })
        return out

    def _stream(self, index):
        try:
            return self._call(lambda p: p.sink_input_info(index))
        except pulsectl.PulseIndexError:
            return None

    def set_app_volume(self, index, vol):
        si = self._stream(index)
        if si:
            self._call(lambda p: p.volume_set_all_chans(si, max(0.0, min(1.5, vol))))

    def set_app_mute(self, index, mute):
        si = self._stream(index)
        if si:
            self._call(lambda p: p.mute(si, mute))

    def move_app(self, index, strip):
        """Send an app stream to an input strip (virtual sink) or straight to an output."""
        sink = self.node(strip) if strip and is_device_sink(strip["kind"]) else None
        if sink is None:
            return
        try:
            self._call(lambda p: p.sink_input_move(index, sink.index))
        except pulsectl.PulseOperationFailed as e:
            print(f"couldn't move stream {index}: {e}", flush=True)

    # ------------------------------------------------------------- events

    def _events(self):
        while not self._stop:
            try:
                with pulsectl.Pulse("Mixdeck events") as p:
                    p.event_mask_set("sink", "source", "sink_input", "server")
                    p.event_callback_set(lambda ev: self.on_event(ev.facility, ev.t))
                    p.event_listen()
            except Exception as e:
                print(f"pulse event listener: {e}; retrying", flush=True)
                time.sleep(2)

    def close(self):
        self._stop = True
        try:
            self.pulse.close()
        except Exception:
            pass
