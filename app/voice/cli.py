"""语音模块 CLI 入口。"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys

from app.voice.config import VoiceConfig
from app.voice.service import VoiceService

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="知行车秘 — 语音模块 CLI")
    parser.add_argument(
        "--list-devices", action="store_true", help="列出可用麦克风设备"
    )
    parser.add_argument("--device", type=int, default=None, help="麦克风设备索引")
    return parser.parse_args(argv)


async def _show_devices(svc: VoiceService) -> None:
    """列出可用麦克风设备并退出。"""
    devices = await svc.get_devices()
    if not devices:
        print("No input devices found.")
        return
    for d in devices:
        print(f"  {d['index']}: {d['name']} ({d['channels']} channels)")


async def _resolve_device(svc: VoiceService, device: int) -> int:
    """校验 device 索引，不合法则退出。"""
    devices = await svc.get_devices()
    valid_indices = {d["index"] for d in devices}
    if device not in valid_indices:
        print(
            f"Error: device index {device} not found. "
            "Use --list-devices to see available devices."
        )
        sys.exit(1)
    return device


def _print_transcription(text: str, confidence: float) -> None:
    print(f"[VAD:speech     ] {text} (conf={confidence:.2f})")


async def _monitor_pipeline(svc: VoiceService) -> None:
    """监控流水线状态，打印 VAD 状态变化。"""
    last_status = ""
    try:
        while True:
            st = svc.status
            vad = st.get("vad_status", "")
            if vad != last_status:
                print(f"[VAD:{vad:14s}]")
                last_status = vad
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        pass


async def _run_cli(args: argparse.Namespace) -> None:
    temp_svc = VoiceService()
    if args.list_devices:
        await _show_devices(temp_svc)
        return

    cfg = VoiceConfig.load()
    if args.device is not None:
        cfg.device_index = await _resolve_device(temp_svc, args.device)

    svc = VoiceService(config=cfg)
    ok = await svc.start(on_transcription=_print_transcription)
    if not ok:
        print(
            "[WARN] Voice pipeline unavailable (ASR model/config disabled).",
            file=sys.stderr,
        )
        return

    print("[INFO] Voice pipeline started. Press Ctrl+C to stop.")
    await _monitor_pipeline(svc)
    await svc.stop()
    print("[INFO] Stopped.")


def main(argv: list[str] | None = None) -> None:
    """CLI 入口。"""
    args = _parse_args(argv)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run_cli(args))
