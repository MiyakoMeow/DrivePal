"""测试 voice CLI 参数解析。"""

from app.voice.cli import _parse_args


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
