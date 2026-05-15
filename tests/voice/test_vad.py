"""测试 VAD 引擎。"""

from app.voice.vad import VADEngine


def test_vad_rejects_empty_frame():
    """静音帧应返回 silence。"""
    eng = VADEngine()
    silence_frame = b"\x00" * 960
    assert not eng.is_speech(silence_frame)


def test_vad_wrong_frame_size():
    """错误大小的帧应返回 False。"""
    eng = VADEngine()
    assert not eng.is_speech(b"\x00" * 100)
