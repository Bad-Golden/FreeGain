"""The vocal must keep flowing: a processing error passes it through, and a
dead audio stream (USB hiccup, driver reset, unplugged device) restarts."""

import numpy as np
import pytest

import audio_engine
from audio_engine import AudioEngine
from roomsim import FS, echo, music, room, voice


class FakeStream:
    def __init__(self, fake_sd, **kwargs):
        self.sd = fake_sd
        self.kwargs = kwargs
        self.active = False
        self.closed = False

    def start(self):
        if self.sd.device_gone:
            raise RuntimeError("Error opening stream: device unavailable")
        self.active = True
        self.sd.streams.append(self)

    def stop(self):
        self.active = False

    def close(self):
        self.closed = True


class FakeSD:
    def __init__(self):
        self.device_gone = False
        self.streams = []

    def query_devices(self, device=None, kind=None):
        return {"name": "Fake USB", "max_input_channels": 18, "default_samplerate": 48000.0}

    def Stream(self, **kwargs):  # noqa: N802 -- mirrors sounddevice
        return FakeStream(self, **kwargs)


@pytest.fixture
def fake_sd(monkeypatch):
    sd = FakeSD()
    monkeypatch.setattr(audio_engine, "_sd", lambda: sd)
    return sd


def feed(engine, mic, ref, block=512):
    out = np.zeros(len(mic))
    for i in range(0, len(mic) - block + 1, block):
        od = np.zeros((block, 1), np.float32)
        engine._callback(np.stack([mic[i:i + block], ref[i:i + block]], 1).astype(np.float32),
                         od, block, None, None)
        out[i:i + block] = od[:, 0]
    return out


def test_processing_error_passes_the_vocal_through(monkeypatch):
    engine = AudioEngine(sample_rate=FS)
    v = voice(1)

    def broken(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(engine.filter, "process", broken)
    out = feed(engine, v, np.zeros_like(v))
    assert engine.callback_errors > 0
    assert "boom" in engine.last_callback_error
    assert np.allclose(out[:len(v) // 512 * 512], v[:len(v) // 512 * 512], atol=1e-6)
    assert engine.diagnostics()["callback_errors"] == engine.callback_errors


def test_dead_stream_is_restarted(fake_sd):
    engine = AudioEngine()
    engine.start()
    first = engine.stream
    assert engine.check_stream() is None            # healthy: nothing to do
    first.active = False                              # driver killed it
    engine._last_restart_try = 0
    message = engine.check_stream()
    assert "running again" in message
    assert engine.stream is not first and engine.stream.active
    assert engine.stream_restarts == 1
    engine.stop()


def test_keeps_retrying_while_the_device_is_gone(fake_sd):
    engine = AudioEngine()
    engine.start()
    engine.stream.active = False
    fake_sd.device_gone = True
    for _ in range(3):
        engine._last_restart_try = 0
        assert "reconnecting" in engine.check_stream()
        assert engine.stream is None
    fake_sd.device_gone = False                       # plugged back in
    engine._last_restart_try = 0
    assert "running again" in engine.check_stream()
    assert engine.stream.active
    engine.stop()


def test_retries_are_spaced_out(fake_sd):
    engine = AudioEngine()
    engine.start()
    engine.stream.active = False
    fake_sd.device_gone = True
    engine._last_restart_try = 0
    assert engine.check_stream()                      # first try
    assert engine.check_stream() is None              # too soon for another
    engine.stop()


def test_explicit_stop_is_not_undone(fake_sd):
    engine = AudioEngine()
    engine.start()
    engine.stop()
    engine._last_restart_try = 0
    assert engine.check_stream() is None
    assert engine.stream is None


def test_restart_keeps_what_was_learned(fake_sd):
    engine = AudioEngine()
    engine.start()
    x = music(4)
    feed(engine, echo(x, room(12, 60)), x)
    learned = engine.filter
    taps = np.abs(learned.W).sum()
    assert taps > 0
    engine.stream.active = False
    engine._last_restart_try = 0
    engine.check_stream()
    assert engine.filter is learned and np.abs(engine.filter.W).sum() == taps
    engine.stop()
