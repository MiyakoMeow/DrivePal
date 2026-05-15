"""测试 voice CLI 参数解析。"""

import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from app.voice.cli import _parse_args, _run_cli
from app.voice.service import VoiceService


def test_parse_args_defaults():
    """Given 无参数, When _parse_args(), Then list_devices=False, device=None。"""
    args = _parse_args([])
    assert args.list_devices is False
    assert args.device is None


def test_parse_args_list_devices():
    """Given --list-devices, When _parse_args(), Then list_devices=True。"""
    args = _parse_args(["--list-devices"])
    assert args.list_devices is True


def test_parse_args_device():
    """Given --device 1, When _parse_args(), Then device=1。"""
    args = _parse_args(["--device", "1"])
    assert args.device == 1


def test_run_cli_device_not_found_exits():
    """Given 不存在的 device 索引, When _run_cli, Then sys.exit(1)。"""
    args = _parse_args(["--device", "99"])
    with (
        patch.object(VoiceService, "get_devices", new_callable=AsyncMock, return_value=[
            {"index": 0, "name": "Mic", "channels": 1},
        ]),
        pytest.raises(SystemExit) as exc_info,
    ):
        asyncio.run(_run_cli(args))
    assert exc_info.value.code == 1


def test_list_devices_output():
    """Given --list-devices, When _run_cli, Then 打印设备信息不崩。"""
    args = _parse_args(["--list-devices"])
    with patch.object(VoiceService, "get_devices", new_callable=AsyncMock, return_value=[
        {"index": 0, "name": "USB Mic", "channels": 1},
        {"index": 1, "name": "Built-in", "channels": 2},
    ]):
        asyncio.run(_run_cli(args))
