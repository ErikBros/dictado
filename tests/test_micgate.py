from dictado.micgate import MicGate


class FakeVol:
    def __init__(self, mute, vol):
        self.mute, self.vol = mute, vol

    def GetMute(self): return self.mute
    def SetMute(self, m, ctx): self.mute = m
    def GetMasterVolumeLevelScalar(self): return self.vol
    def SetMasterVolumeLevelScalar(self, v, ctx): self.vol = v


def gate(eps, **kw):
    return MicGate("Anker PowerConf", lister=lambda: eps, sync=True, **kw)


def test_muted_mic_opened_and_restored():
    v = FakeVol(1, 0.0)
    g = gate([("Headset (Zone Vibe 100)", FakeVol(1, 0.0)), ("Microphone (Anker PowerConf C200)", v)])
    assert g.open() is True
    assert v.mute == 0 and v.vol == 0.8
    g.restore()
    assert v.mute == 1 and v.vol == 0.0


def test_live_mic_untouched():
    v = FakeVol(0, 0.6)
    g = gate([("Microphone (Anker PowerConf C200)", v)])
    assert g.open() is False
    g.restore()
    assert v.mute == 0 and v.vol == 0.6


def test_unmuted_but_zero_volume_raised():
    v = FakeVol(0, 0.0)
    g = gate([("Microphone (Anker PowerConf C200)", v)])
    assert g.open() is True and v.vol == 0.8
    g.restore()
    assert v.vol == 0.0


def test_user_changed_during_recording_not_reverted():
    v = FakeVol(1, 0.0)
    g = gate([("Microphone (Anker PowerConf C200)", v)])
    g.open()
    v.vol = 0.5  # the user moved the slider mid-recording
    g.restore()
    assert v.vol == 0.5


def test_missing_endpoint_is_noop():
    g = gate([("Headset (Zone Vibe 100)", FakeVol(1, 0.0))])
    assert g.open() is False
    g.restore()


def test_lister_error_is_noop():
    def boom():
        raise OSError("COM down")
    g = MicGate("Anker", lister=boom, sync=True)
    assert g.open() is False
    g.restore()


def test_disabled():
    v = FakeVol(1, 0.0)
    g = gate([("Microphone (Anker PowerConf C200)", v)], enabled=False)
    assert g.open() is False and v.mute == 1


def test_restore_waits_for_slow_open():
    import time
    v = FakeVol(1, 0.0)

    def slow_lister():
        time.sleep(0.2)
        return [("Microphone (Anker PowerConf C200)", v)]
    g = MicGate("Anker PowerConf", lister=slow_lister)  # real worker thread
    fut = g._pool.submit(g._open)  # open still running when restore is requested
    g.restore()
    fut.result()
    assert v.mute == 1 and v.vol == 0.0


def test_empty_name_never_touches_any_mic():
    v = FakeVol(1, 0.0)
    g = MicGate("", lister=lambda: [("Microphone (Anker PowerConf C200)", v)], sync=True)
    assert g.open() is False and v.mute == 1
