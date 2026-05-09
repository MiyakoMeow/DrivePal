"""多用户隔离测试."""

import pytest

from app.config import user_data_dir
from app.storage.init_data import init_user_dir
from app.storage.jsonl_store import JSONLinesStore


@pytest.mark.asyncio
async def test_users_data_isolated(tmp_path, monkeypatch):
    """两个用户各自写入，读取互不干扰。"""
    monkeypatch.setattr("app.config.DATA_ROOT", tmp_path)
    monkeypatch.setattr("app.storage.init_data.DATA_ROOT", tmp_path)

    init_user_dir("alice")
    init_user_dir("bob")

    store_a = JSONLinesStore(user_dir=user_data_dir("alice"), filename="events.jsonl")
    await store_a.append({"event": "alice_test"})

    store_b = JSONLinesStore(user_dir=user_data_dir("bob"), filename="events.jsonl")
    await store_b.append({"event": "bob_test"})

    events_a = await store_a.read_all()
    events_b = await store_b.read_all()
    assert len(events_a) == 1
    assert events_a[0]["event"] == "alice_test"
    assert len(events_b) == 1
    assert events_b[0]["event"] == "bob_test"


@pytest.mark.asyncio
async def test_init_user_dir_creates_all_files(tmp_path, monkeypatch):
    """init_user_dir 创建完整目录结构。"""
    monkeypatch.setattr("app.config.DATA_ROOT", tmp_path)
    monkeypatch.setattr("app.storage.init_data.DATA_ROOT", tmp_path)

    u_dir = init_user_dir("testuser")
    assert u_dir.exists()
    assert (u_dir / "events.jsonl").exists()
    assert (u_dir / "strategies.toml").exists()
    assert (u_dir / "scenario_presets.toml").exists()


def test_migrate_legacy_moves_files(tmp_path, monkeypatch):
    """_migrate_legacy 将平铺文件迁至 data/users/default/。"""
    from app.storage.init_data import _migrate_legacy

    monkeypatch.setattr("app.config.DATA_ROOT", tmp_path)
    monkeypatch.setattr("app.storage.init_data.DATA_ROOT", tmp_path)

    (tmp_path / "events.jsonl").write_text("")
    (tmp_path / "strategies.toml").write_text("")
    assert _migrate_legacy() is True
    assert (tmp_path / "users" / "default" / "events.jsonl").exists()
    assert not (tmp_path / "events.jsonl").exists()


def test_user_data_dir_path(tmp_path, monkeypatch):
    """user_data_dir 返回正确的 per-user 路径。"""
    monkeypatch.setattr("app.config.DATA_ROOT", tmp_path / "data")
    u_dir = user_data_dir("alice")
    assert u_dir.name == "alice"
    assert "users" in str(u_dir)
