"""Stereo peak meters from PipeWire (through pipewire-pulse peak-detect record streams).

Runs its own asyncio loop on a background thread. `set_targets` says what to watch;
`levels` holds the latest (left, right) peak, 0.0-1.0 linear, per strip id.
Meters only run while something is showing them, so the mic isn't kept open for nothing.
"""
import asyncio
import threading

import pulsectl_asyncio
from pulsectl import _pulsectl as c

from .audio import METER_CLIENT

RATE = 30


async def peak_stereo(pulse, source, stream_idx=None):
    """Like PulseAsync.subscribe_peak_sample, but two channels: yields (left, right)."""
    proplist = c.pa.proplist_from_string("")
    ss = c.PA_SAMPLE_SPEC(format=c.PA_SAMPLE_FLOAT32NE, rate=RATE, channels=2)
    s = c.pa.stream_new_with_proplist(pulse._ctx, "peak detect", c.byref(ss), None, proplist)
    c.pa.proplist_free(proplist)
    queue = asyncio.Queue()

    @c.PA_STREAM_REQUEST_CB_T
    def read_cb(s, nbytes, _userdata):
        bs = c.c_int(nbytes)
        buff = c.c_void_p()
        c.pa.stream_peek(s, buff, c.byref(bs))
        try:
            if not buff or bs.value < 8:
                return
            f = c.cast(buff, c.POINTER(c.c_float))
            queue.put_nowait((f[0], f[1]))
        finally:
            if bs.value:
                c.pa.stream_drop(s)

    if stream_idx is not None:
        c.pa.stream_set_monitor_stream(s, stream_idx)
    c.pa.stream_set_read_callback(s, read_cb, None)
    flags = c.PA_STREAM_DONT_MOVE | c.PA_STREAM_PEAK_DETECT | c.PA_STREAM_ADJUST_LATENCY
    try:
        c.pa.stream_connect_record(s, str(source).encode(), c.PA_BUFFER_ATTR(fragsize=8, maxlength=2**32 - 1), flags)
    except c.pa.CallError:
        c.pa.stream_unref(s)
        raise
    try:
        while True:
            yield await pulse._wait_disconnect_or(queue.get())
    finally:
        try:
            c.pa.stream_disconnect(s)
        except c.pa.CallError:
            pass
        c.pa.stream_unref(s)


class Meters:
    def __init__(self):
        self.levels = {}
        self._targets = {}  # id -> (source name, stream index or None)
        self._tasks = {}
        self._pulse = None
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="meters").start()

    def set_targets(self, targets):
        """targets: {strip id: (source name, stream index or None)}; {} stops everything."""
        self.loop.call_soon_threadsafe(self._apply, dict(targets))

    def _apply(self, targets):
        for sid, task in list(self._tasks.items()):
            if self._targets.get(sid) != targets.get(sid) or task.done():
                task.cancel()
                del self._tasks[sid]
                self.levels.pop(sid, None)
        self._targets = targets
        for sid, target in targets.items():
            if sid not in self._tasks:
                self._tasks[sid] = self.loop.create_task(self._watch(sid, *target))

    async def _connect(self):
        if self._pulse is None:
            p = pulsectl_asyncio.PulseAsync(METER_CLIENT)
            await p.connect()
            self._pulse = p
        return self._pulse

    async def _watch(self, sid, source, stream_idx):
        try:
            pulse = await self._connect()
            async for lr in peak_stereo(pulse, source, stream_idx):
                self.levels[sid] = lr
        except asyncio.CancelledError:
            raise
        except Exception:
            # Source gone or server restarted: forget the connection; the next
            # set_targets call restarts this meter
            self.levels.pop(sid, None)
            if self._pulse is not None and not self._pulse.connected:
                self._pulse = None
