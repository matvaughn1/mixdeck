# Mixdeck

A Voicemeeter-style mixer for PipeWire, with Behringer X-Touch control.

- **Inputs:** hardware inputs and virtual inputs (apps play into these). Each has a
  fader, meter, mute, solo, pan, A/B routing to the outputs, and a channel picker:
  stereo, mono (L+R mixed), or one input of an audio interface. Add the same
  interface more than once to give each input its own strip.
- **Apps:** a strip for each app playing sound, with a "Send to" picker. The choice is
  remembered per app.
- **Outputs:** hardware outputs (A1, A2…) and virtual outputs (B1… — mics other apps
  can record, e.g. for calls).
- Right-click a strip's name for colour, rename, "new apps play here", move and remove.
  Drag a strip by its name to reorder. Double-click a fader for 0 dB.
- Settings are saved as they change, in `~/.config/mixdeck/config.json`.

## X-Touch

Press **USER** to switch the X-Touch between this PC and the remote Mac link from
[xtouch-remote](https://github.com/matvaughn1/xtouch-remote). On this PC: faders =
volume (in strip order, banked with Bank/Channel ◀▶), MUTE, SOLO, REC = A1 route,
V-pots = pan, scribble strips show name, level and strip colour, and the master fader
is the leftmost hardware output. Handing back restores what the Mac last showed.

## Install

```
./install.sh      # mixdeck on PATH, app menu entry, start at login (tray)
mixdeck           # open the window
```

Needs Python 3, PySide6, python-pulsectl, python-pulsectl-asyncio, PipeWire with
pipewire-pulse, and alsa-utils.
