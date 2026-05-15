"""测试 VoiceService 生命周期."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.voice.config import VoiceConfig
from app.voice.service import VoiceService


def _cfg(**kwargs) -> VoiceConfig:
    """创建带覆盖值的 VoiceConfig（避免 MagicMock 导致 TOML 序列化失败）。"""
    c = VoiceConfig()
    for k, v in kwargs.items():
        if k == "asr" and v is None:
            c.asr = None
        else:
            setattr(c, k, v)
    return c


@pytest.mark.asyncio
async def test_start_enabled_false_noop():
    """Given enabled=False, When start(), Then 不创建任何东西，返回 False。"""
    svc = VoiceService(config=_cfg(enabled=False))
    result = await svc.start()
    assert result is False
    assert svc._pipeline is None


@pytest.mark.asyncio
async def test_stop_idempotent():
    """Given 未启动, When stop(), Then 不抛异常。"""
    svc = VoiceService(config=_cfg(enabled=True))
    await svc.stop()  # 不应抛


@pytest.mark.asyncio
async def test_status_reflects_state():
    """Given 启动后, When status, Then 反映实际状态。"""
    svc = VoiceService.__new__(VoiceService)
    svc._config = _cfg()
    svc._enabled = True
    svc._running = True
    svc._pipeline = MagicMock()
    svc._recorder = MagicMock()
    svc._vad_status = "speech"
    svc._transcription_history = []
    svc._consume_task = MagicMock()

    st = svc.status
    assert st["enabled"] is True
    assert st["running"] is True
    assert st["vad_status"] == "speech"
    assert "device_index" in st
    assert "config" in st
    assert isinstance(st["config"], dict)


@pytest.mark.asyncio
async def test_get_transcriptions_returns_history():
    """Given 有历史, When get_transcriptions(2), Then 返回最近 2 条。"""
    svc = VoiceService.__new__(VoiceService)
    svc._config = _cfg()
    svc._transcription_history = [
        {"text": "a", "confidence": 0.9, "timestamp": "1"},
        {"text": "b", "confidence": 0.8, "timestamp": "2"},
        {"text": "c", "confidence": 0.95, "timestamp": "3"},
    ]
    svc._enabled = True
    svc._running = False
    svc._pipeline = None
    svc._recorder = None
    svc._consume_task = None
    svc._vad_status = "idle"

    result = await svc.get_transcriptions(limit=2)
    assert len(result) == 2
    assert result[-1]["text"] == "c"


@pytest.mark.asyncio
async def test_get_devices_returns_list():
    """Given pyaudio 可用, When get_devices(), Then 返设备列表。"""
    mock_pyaudio = MagicMock()
    mock_pa = MagicMock()
    mock_pyaudio.PyAudio.return_value = mock_pa
    mock_pa.get_device_count.return_value = 2
    mock_pa.get_device_info_by_index.side_effect = [
        {"index": 0, "name": "Mic", "maxInputChannels": 1},
        {"index": 1, "name": "Speaker", "maxInputChannels": 0},
    ]
    svc = VoiceService(config=_cfg(enabled=True))
    with patch.dict("sys.modules", {"pyaudio": mock_pyaudio}):
        devices = await svc.get_devices()
        assert len(devices) == 1  # 仅输入设备
        assert devices[0]["name"] == "Mic"


@pytest.mark.asyncio
async def test_update_config_invalid_vad_mode():
    """Given vad_mode=9, When update_config(), Then 抛 ValueError。"""
    svc = VoiceService(config=_cfg(enabled=True))
    with pytest.raises(ValueError, match="vad_mode must be 0-3"):
        await svc.update_config({"vad_mode": 9})


@pytest.mark.asyncio
async def test_toggle_recording_start():
    """Given 未启动, When toggle_recording(True), Then 调用 start。"""
    svc = VoiceService(config=_cfg(enabled=True))
    svc.start = AsyncMock(return_value=True)
    result = await svc.toggle_recording(start=True)
    assert result is True


@pytest.mark.asyncio
async def test_toggle_recording_stop():
    """Given 未启动, When toggle_recording(False), Then 调用 stop。"""
    svc = VoiceService(config=_cfg(enabled=True))
    svc.stop = AsyncMock()
    result = await svc.toggle_recording(start=False)
    assert result is False


@pytest.mark.asyncio
async def test_update_config_invalid_min_confidence():
    """Given min_confidence=1.5, When update_config(), Then 抛 ValueError。"""
    svc = VoiceService(config=_cfg(enabled=True))
    with pytest.raises(ValueError, match="min_confidence must be 0.0-1.0"):
        await svc.update_config({"min_confidence": 1.5})


@pytest.mark.asyncio
async def test_update_config_unknown_key():
    """Given 未知 key, When update_config(), Then 抛 ValueError。"""
    svc = VoiceService(config=_cfg(enabled=True))
    with pytest.raises(ValueError, match="Unknown config key"):
        await svc.update_config({"nonexistent": 1})
