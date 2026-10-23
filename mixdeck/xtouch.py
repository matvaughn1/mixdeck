"""Behringer X-Touch (Mackie Control mode) for Mixdeck.

Always listens to the X-Touch through an ALSA sequencer client ("Mixdeck X-Touch");
read subscriptions are shared, so this doesn't disturb the link to the Mac.
USER switches between:
  PC mode  - the X-Touch drives Mixdeck. xtouch-rtpmidi-link.sh is paused (same pause
             file xtouch-vegas uses), the Mac links are removed and restored afterwards.
  Mac mode - hands the surface back to the Mac link.

In PC mode, per channel: fader = volume, MUTE, SOLO, REC = route to A1, V-pot = pan,
scribble strip = name and level, meters. Master fader = first hardware output.
Bank ◀/▶ and Channel ◀/▶ scroll through the strips.

Runs on its own thread. `host` is the Backend: the thread reads `host.surface()` (a
snapshot list, replaced as a whole by the main thread) and calls host.xt_* methods,
which only queue work for the main thread.
"""
import ctypes
import os
import re
import select
import subprocess
import threading
import time

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
PAUSE_FILE = os.path.join(RUNTIME, "xtouch-link.pause")   # read by xtouch-rtpmidi-link.sh
MODE_FILE = os.path.join(RUNTIME, "mixdeck-xtouch.active")  # we own the pause file
XTOUCH_RE = r"^x-touch$"  # keep in step with xtouch-rtpmidi-link.sh

REC, SOLO, MUTE, SELECT = 0x00, 0x08, 0x10, 0x18
BANK_L, BANK_R, CHAN_L, CHAN_R = 0x2E, 0x2F, 0x30, 0x31
USER_BTN = 0x45
TOUCH = 0x68  # 0x68-0x6F strips, 0x70 master
MASTER = 8
HDR = [0xF0, 0x00, 0x00, 0x66, 0x14]
OFF, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)
COLOR_CODE = {"red": RED, "green": GREEN, "yellow": YELLOW, "blue": BLUE,
              "magenta": MAGENTA, "cyan": CYAN, "white": WHITE}

# ------------------------------------------------------------- ALSA seq ---

asound = ctypes.CDLL("libasound.so.2")
CAPS = 0x01 | 0x02 | 0x10 | 0x20 | 0x40
PORT_TYPE = (1 << 1) | (1 << 20)
ADDR_SUBSCRIBERS, ADDR_UNKNOWN, QUEUE_DIRECT = 254, 253, 253


class Addr(ctypes.Structure):
    _fields_ = [("client", ctypes.c_ubyte), ("port", ctypes.c_ubyte)]


class Event(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("tag", ctypes.c_ubyte),
                ("queue", ctypes.c_ubyte), ("time", ctypes.c_ubyte * 8),
                ("source", Addr), ("dest", Addr), ("data", ctypes.c_ubyte * 12)]


class PollFd(ctypes.Structure):
    _fields_ = [("fd", ctypes.c_int), ("events", ctypes.c_short), ("revents", ctypes.c_short)]


vp = ctypes.c_void_p
asound.snd_seq_event_input.argtypes = [vp, ctypes.POINTER(ctypes.POINTER(Event))]
asound.snd_seq_event_output_direct.argtypes = [vp, ctypes.POINTER(Event)]
asound.snd_seq_create_simple_port.argtypes = [vp, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint]
for _f in ("connect_from", "connect_to", "disconnect_from", "disconnect_to"):
    getattr(asound, f"snd_seq_{_f}").argtypes = [vp, ctypes.c_int, ctypes.c_int, ctypes.c_int]
asound.snd_seq_poll_descriptors.argtypes = [vp, ctypes.POINTER(PollFd), ctypes.c_uint, ctypes.c_short]
asound.snd_midi_event_encode.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, ctypes.POINTER(Event)]
asound.snd_midi_event_encode.restype = ctypes.c_long
asound.snd_midi_event_decode.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, ctypes.POINTER(Event)]
asound.snd_midi_event_decode.restype = ctypes.c_long
asound.snd_midi_event_reset_encode.argtypes = [vp]
asound.snd_midi_event_no_status.argtypes = [vp, ctypes.c_int]
asound.snd_seq_set_client_name.argtypes = [vp, ctypes.c_char_p]
asound.snd_seq_nonblock.argtypes = [vp, ctypes.c_int]
asound.snd_seq_client_id.argtypes = [vp]


def aconnect_list():
    return subprocess.run(["aconnect", "-l"], capture_output=True, text=True).stdout


def find_xtouch():
    for m in re.finditer(r"^client (\d+): '([^']*)' \[type=kernel", aconnect_list(), re.M):
        if re.search(XTOUCH_RE, m.group(2), re.I):
            return int(m.group(1))
    return None


def aconnect(src, dst, on):
    subprocess.run(["aconnect", src, dst] if on else ["aconnect", "-d", src, dst], capture_output=True)


def rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def db_text(vol):
    import math
    if vol <= 0.0005:
        return "-inf"
    db = 60 * math.log10(vol)
    return f"{0.0 if abs(db) < 0.05 else db:.1f}"


def meter_level(peak):
    """Linear peak -> X-Touch meter segment 0-12 (-60 dB .. 0 dB)."""
    import math
    if peak <= 0.001:
        return 0
    return max(0, min(12, round((20 * math.log10(peak) + 60) / 5)))


class XTouch(threading.Thread):
    def __init__(self, host):
        super().__init__(daemon=True, name="xtouch")
        self.host = host
        self.active = False
        self.xt = None
        self.bank = 0
        self.saved_links = []
        self.touched = set()
        self.shown = {}
        # What the Mac (or other DAW) last put on the surface, so it can be restored when
        # the X-Touch is handed back: Mackie messages by key, plus the scribble-strip text
        self.host_srcs = set()
        self.mac = {}
        self.mac_lcd = bytearray(b" " * 112)
        self.mac_lcd_seen = False
        self._requests = []  # mode changes asked for by the UI
        self._lock = threading.Lock()

        self.seq = vp()
        if asound.snd_seq_open(ctypes.byref(self.seq), b"default", 3, 0) < 0:
            raise RuntimeError("can't open the ALSA sequencer")
        asound.snd_seq_set_client_name(self.seq, b"Mixdeck X-Touch")
        asound.snd_seq_nonblock(self.seq, 1)
        self.port = asound.snd_seq_create_simple_port(self.seq, b"control", CAPS, PORT_TYPE)
        self.my_id = asound.snd_seq_client_id(self.seq)
        self.enc, self.dec = vp(), vp()
        asound.snd_midi_event_new(1024, ctypes.byref(self.enc))
        asound.snd_midi_event_new(1024, ctypes.byref(self.dec))
        asound.snd_midi_event_no_status(self.dec, 1)
        self.pfd = PollFd()
        asound.snd_seq_poll_descriptors(self.seq, ctypes.byref(self.pfd), 1, select.POLLIN)

        # A leftover marker means we died in PC mode: give the link back
        if os.path.exists(MODE_FILE):
            rm(MODE_FILE)
            rm(PAUSE_FILE)

    # ---------------------------------------------------------- public API

    @property
    def present(self):
        return self.xt is not None

    def request_mode(self, pc):
        with self._lock:
            self._requests.append(bool(pc))

    def shutdown(self):
        with self._lock:
            self._requests.append(None)

    # ----------------------------------------------------------------- MIDI

    def send(self, data):
        data = bytes(data)
        asound.snd_midi_event_reset_encode(self.enc)
        ev = Event()
        while data:
            n = asound.snd_midi_event_encode(self.enc, data, len(data), ctypes.byref(ev))
            if n <= 0:
                break
            data = data[n:]
            if ev.type != 0:
                ev.source.port = self.port
                ev.dest.client, ev.dest.port = ADDR_SUBSCRIBERS, ADDR_UNKNOWN
                ev.queue = QUEUE_DIRECT
                asound.snd_seq_event_output_direct(self.seq, ctypes.byref(ev))
                ev = Event()

    def read_events(self):
        """Pending input as (source "client:port", raw MIDI bytes)."""
        out = []
        evp = ctypes.POINTER(Event)()
        buf = ctypes.create_string_buffer(1024)
        while True:
            r = asound.snd_seq_event_input(self.seq, ctypes.byref(evp))
            if r < 0:
                if r == -28:  # ENOSPC overrun
                    continue
                return out
            src = f"{evp.contents.source.client}:{evp.contents.source.port}"
            n = asound.snd_midi_event_decode(self.dec, buf, 1024, evp)
            if n > 0:
                out.append((src, buf.raw[:n]))

    # surface primitives
    def strip_text(self, ch, row, text):
        data = text[:7].center(7).encode("ascii", "replace")
        self.send(HDR + [0x12, row * 0x38 + ch * 7] + list(data) + [0xF7])

    def fader(self, ch, vol):
        v = max(0, min(16383, round(min(vol, 1.0) * 16383)))
        self.send([0xE0 | ch, v & 0x7F, v >> 7])

    def led(self, note, on):
        self.send([0x90, note, 0x7F if on else 0])

    def display(self, text):
        text = text.upper().ljust(12)[:12]
        ccs = [0x4B, 0x4A] + list(range(0x49, 0x3F, -1))
        for cc, ch in zip(ccs, text):
            self.send([0xB0, cc, ord(ch) & 0x3F])

    def blank(self):
        for n in list(range(0x00, 0x20)) + list(range(0x28, 0x66)):
            self.led(n, False)
        for ch in range(8):
            self.send([0xB0, 0x30 + ch, 0])
            self.send([0xD0, ch << 4])
        for ch in range(9):
            self.fader(ch, 0)
        self.send(HDR + [0x12, 0] + [0x20] * 112 + [0xF7])
        self.send(HDR + [0x72] + [OFF] * 8 + [0xF7])
        self.display("")

    # ------------------------------------------------- the Mac's surface state

    def cache_host(self, msg):
        """Remember the latest of each thing the Mac sets on the surface (meters skipped)."""
        st = msg[0] & 0xF0
        if st in (0x80, 0x90) and len(msg) >= 3:
            self.mac[("note", msg[1])] = bytes([0x90, msg[1], msg[2] if st == 0x90 else 0])
        elif st == 0xE0 and len(msg) >= 3:
            self.mac[("fader", msg[0] & 0x0F)] = bytes(msg[:3])
        elif st == 0xB0 and len(msg) >= 3 and (0x30 <= msg[1] < 0x38 or 0x40 <= msg[1] < 0x4C):
            self.mac[("cc", msg[1])] = bytes(msg[:3])
        elif msg[:5] == bytes(HDR) and len(msg) > 7:
            if msg[5] == 0x12:
                off, text = msg[6], msg[7:-1]
                self.mac_lcd[off:off + len(text)] = text[:max(0, 112 - off)]
                self.mac_lcd_seen = True
            elif msg[5] == 0x72:
                self.mac["colors"] = bytes(msg)

    def restore_host(self):
        """Put the Mac's last surface state back (instead of leaving it blank)."""
        self.blank()
        if self.mac_lcd_seen:
            self.send(HDR + [0x12, 0] + list(self.mac_lcd) + [0xF7])
        for msg in list(self.mac.values()):
            self.send(msg)
        print(f"X-Touch: restored {len(self.mac)} Mac controls"
              + (" and strip names" if self.mac_lcd_seen else ""), flush=True)

    # ---------------------------------------------------------------- links

    def other_links(self):
        links, cur_c, cur = set(), None, None
        for line in aconnect_list().splitlines():
            if m := re.match(r"client (\d+):", line):
                cur_c = m.group(1)
            elif m := re.match(r"\s+(\d+) '", line):
                cur = f"{cur_c}:{m.group(1)}"
            elif m := re.match(r"\s+Connecting To: (.*)", line):
                for dst in m.group(1).split(","):
                    links.add((cur, dst.strip().split("[")[0]))
        me, xt = f"{self.my_id}:", f"{self.xt}:0"
        return sorted(l for l in links if xt in l and not (l[0].startswith(me) or l[1].startswith(me)))

    def ensure_listening(self):
        xt = find_xtouch()
        if xt != self.xt:
            print(f"X-Touch {'is client ' + str(xt) if xt is not None else 'gone'}", flush=True)
            if xt is None and self.active:
                self.leave(surface=False)
            self.xt = xt
            self.host.xt_changed()
        if xt is not None:
            asound.snd_seq_connect_from(self.seq, self.port, xt, 0)
            if self.active:
                asound.snd_seq_connect_to(self.seq, self.port, xt, 0)
            else:
                # also listen to whatever feeds the X-Touch (the Mac link) to keep a copy
                for src, dst in self.other_links():
                    if dst == f"{xt}:0":  # re-subscribe every pass: the source may have restarted
                        c, p = (int(x) for x in src.split(":"))
                        asound.snd_seq_connect_from(self.seq, self.port, c, p)
                        self.host_srcs.add(src)

    def enter(self):
        if self.xt is None or self.active:
            return
        if os.path.exists(PAUSE_FILE) and not os.path.exists(MODE_FILE):
            print("X-Touch link paused by something else (xtouch-vegas?); staying in Mac mode", flush=True)
            return
        open(PAUSE_FILE, "w").close()
        open(MODE_FILE, "w").close()
        time.sleep(0.2)  # let the link script finish any pass it's in
        self.saved_links = self.other_links()
        for src, dst in self.saved_links:
            aconnect(src, dst, False)
        asound.snd_seq_connect_to(self.seq, self.port, self.xt, 0)
        self.active = True
        self.shown = {}
        self.blank()
        print("X-Touch: PC mode", flush=True)
        self.host.xt_changed()

    def leave(self, surface=True):
        if not self.active:
            return
        if surface and self.xt is not None:
            self.restore_host()
            asound.snd_seq_disconnect_to(self.seq, self.port, self.xt, 0)
            for src, dst in self.saved_links:
                aconnect(src, dst, True)
        self.saved_links = []
        self.active = False
        rm(MODE_FILE)
        rm(PAUSE_FILE)
        print("X-Touch: Mac mode", flush=True)
        self.host.xt_changed()

    # -------------------------------------------------------------- surface

    def put(self, key, value, fn):
        if self.shown.get(key) != value:
            self.shown[key] = value
            fn()

    def banked(self):
        strips, master = self.host.surface()
        self.bank = max(0, min(self.bank, max(0, len(strips) - 1)))
        return strips[self.bank:self.bank + 8], master, len(strips)

    def refresh(self, meters):
        chans, master, total = self.banked()
        names = [s["name"] for s in chans] + [""] * (8 - len(chans))
        colors = [COLOR_CODE.get(s.get("color"), WHITE) for s in chans] + [OFF] * (8 - len(chans))
        self.put("colors", tuple(colors), lambda: self.send(HDR + [0x72] + colors + [0xF7]))
        for ch in range(8):
            s = chans[ch] if ch < len(chans) else None
            self.put(("name", ch), names[ch], lambda ch=ch: self.strip_text(ch, 0, names[ch]))
            vol = s["vol"] if s else 0.0
            if ch not in self.touched:
                self.put(("fader", ch), round(vol, 3), lambda ch=ch, vol=vol: self.fader(ch, vol))
            text = "" if s is None else "MUTE" if s["mute"] else db_text(vol)
            self.put(("level", ch), text, lambda ch=ch, text=text: self.strip_text(ch, 1, text))
            for base, key in ((MUTE, "mute"), (SOLO, "solo"), (REC, "a1")):
                on = bool(s and s.get(key))
                self.put((key, ch), on, lambda n=base + ch, on=on: self.led(n, on))
            pan = s.get("pan") if s else None
            ring = 0 if pan is None else 1 + round((pan + 1) * 5)
            self.put(("ring", ch), ring, lambda ch=ch, ring=ring: self.send([0xB0, 0x30 + ch, ring]))
            if meters and s:
                self.send([0xD0, (ch << 4) | meter_level(s.get("peak", 0.0))])
        if MASTER not in self.touched:
            mv = master["vol"] if master else 0.0
            self.put(("fader", MASTER), round(mv, 3), lambda: self.fader(MASTER, mv))
        self.put("display", self.bank, lambda: self.display(f"PC{self.bank // 8 + 1:>2}"))
        self.put("user", True, lambda: self.led(USER_BTN, True))

    def target(self, ch):
        chans, master, _ = self.banked()
        if ch == MASTER:
            return master
        return chans[ch] if ch < len(chans) else None

    # ---------------------------------------------------------------- input

    def handle(self, msg):
        status = msg[0] & 0xF0
        if status == 0x90 and len(msg) >= 3:
            note, vel = msg[1], msg[2]
            if note == USER_BTN and vel:
                self.leave() if self.active else self.enter()
                return
            if not self.active:
                return
            if TOUCH <= note <= TOUCH + 8:
                ch = note - TOUCH
                if vel:
                    self.touched.add(ch)
                else:
                    self.touched.discard(ch)
                    self.shown.pop(("fader", ch), None)  # put the motor where the level is
                return
            if not vel:
                return
            if note in (BANK_L, BANK_R, CHAN_L, CHAN_R):
                _, _, total = self.banked()
                step = 8 if note in (BANK_L, BANK_R) else 1
                step = -step if note in (BANK_L, CHAN_L) else step
                self.bank = max(0, min(self.bank + step, max(0, total - 1)))
                self.shown = {k: v for k, v in self.shown.items() if k == "user"}
                return
            for base, action in ((MUTE, "mute"), (SOLO, "solo"), (REC, "a1")):
                if base <= note < base + 8:
                    s = self.target(note - base)
                    if s:
                        self.host.xt_action(action, s["id"])
        elif status == 0xE0 and self.active and len(msg) >= 3:
            s = self.target(msg[0] & 0x0F)
            if s:
                self.host.xt_volume(s["id"], (msg[1] | msg[2] << 7) / 16383)
        elif status == 0xB0 and self.active and len(msg) >= 3 and 0x10 <= msg[1] < 0x18:
            s = self.target(msg[1] - 0x10)
            if s and s.get("pan") is not None:
                speed = msg[2] & 0x3F
                self.host.xt_pan(s["id"], (-speed if msg[2] & 0x40 else speed) * 0.05)

    # ------------------------------------------------------------------ run

    def run(self):
        next_check = next_refresh = next_meter = 0
        while True:
            with self._lock:
                requests, self._requests = self._requests, []
            for pc in requests:
                if pc is None:
                    self.leave()
                    return
                self.enter() if pc else self.leave()
            now = time.monotonic()
            if now >= next_check:
                self.ensure_listening()
                next_check = now + 3
            select.select([self.pfd.fd], [], [], 0.03)
            xt_src = f"{self.xt}:0"
            for src, msg in self.read_events():
                if src != xt_src:
                    if src in self.host_srcs:
                        self.cache_host(msg)
                    continue
                try:
                    self.handle(msg)
                except Exception as e:
                    print(f"X-Touch input error: {e}", flush=True)
            now = time.monotonic()
            if self.active and now >= next_refresh:
                meters = now >= next_meter
                try:
                    self.refresh(meters)
                except Exception as e:
                    print(f"X-Touch refresh error: {e}", flush=True)
                next_refresh = now + 0.05
                if meters:
                    next_meter = now + 0.1
