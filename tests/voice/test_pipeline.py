"""测试 VoicePipeline 编排：VAD → ASR → 文本输出。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.voice.asr import ASRResult
from app.voice.constants import VADStatus
from app.voice.pipeline import VoicePipeline


def _make_pipeline(
    min_confidence: float = 0.5,
    on_transcription=None,
) -> VoicePipeline:
    """构造 mock 依赖的 VoicePipeline。"""
    mock_asr = AsyncMock()
    mock_asr.transcribe.return_value = ASRResult(text="", confidence=0.0)
    mock_asr.close = AsyncMock()

    pipeline = VoicePipeline.__new__(VoicePipeline)
    pipeline._vad = MagicMock()
    pipeline._vad.frame_bytes = 960
    pipeline._expected_frame_bytes = 960
    pipeline._asr = mock_asr
    pipeline._min_confidence = min_confidence
    pipeline._on_transcription = on_transcription
    pipeline._on_vad_status = None
    pipeline._audio_queue = asyncio.Queue()
    pipeline._running = False

    return pipeline


async def _collect_yields(pipeline, max_items: int = 10):
    """从 pipeline.run() 收集最多 max_items 个 yield。"""
    results = []
    done = asyncio.Event()

    async def _run_and_collect():
        async for text in pipeline.run():
            results.append(text)
            if len(results) >= max_items:
                await pipeline.stop()
        done.set()

    task = asyncio.ensure_future(_run_and_collect())
    try:
        await asyncio.wait_for(done.wait(), timeout=2.0)
    except TimeoutError:
        task.cancel()
    return results


class TestPipelineVadAsrYield:
    """正常 VAD → ASR → yield text。"""

    async def test_normal_flow(self):
        """Given 完整语音段（speech_start → speech → speech_end）+ ASR 返回高置信文本，When run，Then yield 该文本。"""
        pipeline = _make_pipeline()
        pipeline._asr.transcribe.return_value = ASRResult(text="你好", confidence=0.9)

        pipeline._vad.process_frame.side_effect = [
            VADStatus.SPEECH_START,
            VADStatus.SPEECH,
            VADStatus.SPEECH_END,
        ]

        frame = b"\x00" * 960
        await pipeline.feed_audio(frame)
        await pipeline.feed_audio(frame)
        await pipeline.feed_audio(frame)

        results = await _collect_yields(pipeline)
        assert results == ["你好"]


class TestPipelineLowConfidence:
    """置信度低于阈值 → 不 yield。"""

    async def test_low_confidence_dropped(self):
        """Given ASR 返回低置信度文本，When run，Then 不 yield。"""
        pipeline = _make_pipeline(min_confidence=0.7)
        pipeline._asr.transcribe.return_value = ASRResult(text="嗯", confidence=0.3)

        pipeline._vad.process_frame.side_effect = [
            VADStatus.SPEECH_START,
            VADStatus.SPEECH_END,
        ]

        frame = b"\x00" * 960
        await pipeline.feed_audio(frame)
        await pipeline.feed_audio(frame)

        results = await _collect_yields(pipeline)
        assert results == []


class TestPipelineEmptyAsrResult:
    """ASR 不可用（返回空结果）→ 不 yield。"""

    async def test_empty_result_dropped(self):
        """Given ASR 返回空文本，When run，Then 不 yield。"""
        pipeline = _make_pipeline()
        pipeline._asr.transcribe.return_value = ASRResult(text="", confidence=0.0)

        pipeline._vad.process_frame.side_effect = [
            VADStatus.SPEECH_START,
            VADStatus.SPEECH_END,
        ]

        frame = b"\x00" * 960
        await pipeline.feed_audio(frame)
        await pipeline.feed_audio(frame)

        results = await _collect_yields(pipeline)
        assert results == []


class TestPipelineFrameSizeMismatch:
    """帧大小不匹配 → 跳过 + warning。"""

    async def test_wrong_size_skipped(self):
        """Given 喂入错误大小帧，When run，Then VAD 未被调用且不 yield。"""
        pipeline = _make_pipeline()

        await pipeline.feed_audio(b"\x00" * 100)

        results = await _collect_yields(pipeline)
        assert results == []
        pipeline._vad.process_frame.assert_not_called()


class TestPipelineCallback:
    """on_transcription 回调被触发。"""

    async def test_callback_fired(self):
        """Given 设置 on_transcription 回调 + 高置信 ASR 结果，When run，Then 回调被调用。"""
        callback = MagicMock()
        pipeline = _make_pipeline(on_transcription=callback)
        pipeline._asr.transcribe.return_value = ASRResult(text="测试", confidence=0.8)

        pipeline._vad.process_frame.side_effect = [
            VADStatus.SPEECH_START,
            VADStatus.SPEECH,
            VADStatus.SPEECH_END,
        ]

        frame = b"\x00" * 960
        await pipeline.feed_audio(frame)
        await pipeline.feed_audio(frame)
        await pipeline.feed_audio(frame)

        await _collect_yields(pipeline)
        callback.assert_called_once_with("测试", 0.8)


class TestPipelineSilenceOnly:
    """空队列/纯静音 → 无 yield。"""

    async def test_silence_no_yield(self):
        """Given VAD 始终返回 silence，When run，Then 不 yield。"""
        pipeline = _make_pipeline()
        pipeline._vad.process_frame.return_value = VADStatus.SILENCE

        frame = b"\x00" * 960
        await pipeline.feed_audio(frame)
        await pipeline.feed_audio(frame)

        results = await _collect_yields(pipeline)
        assert results == []
