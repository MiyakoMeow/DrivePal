"""语音流水线：录音 → VAD → ASR → 文本输出。"""

from app.voice.pipeline import VoicePipeline as VoicePipeline
from app.voice.service import VoiceService as VoiceService
