"""用户身份中间件测试."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from app.api.middleware import UserIdentityMiddleware
from tests.fixtures import (
    MODULES_WITH_DATA_DIR,
    MODULES_WITH_DATA_ROOT,
    reset_all_singletons,
)

if TYPE_CHECKING:
    from collections.abc import Generator


def _make_app() -> FastAPI:
    """创建挂载中间件的测试用 FastAPI 实例."""
    api = FastAPI()
    api.add_middleware(UserIdentityMiddleware)

    @api.get("/whoami")
    async def whoami(request: Request) -> PlainTextResponse:
        return PlainTextResponse(request.state.user_id)

    return api


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    """提供带 UserIdentityMiddleware 的 TestClient."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    target = Path(data_dir)
    with ExitStack() as stack:
        for mod in MODULES_WITH_DATA_DIR:
            stack.enter_context(patch(f"{mod}.DATA_DIR", target))
        for mod in MODULES_WITH_DATA_ROOT:
            stack.enter_context(patch(f"{mod}.DATA_ROOT", target))
        reset_all_singletons()
        with TestClient(_make_app()) as c:
            yield c
        reset_all_singletons()


def test_default_user_id_when_header_missing(client: TestClient) -> None:
    """无 X-User-Id header 时 user_id 应为 default."""
    resp = client.get("/whoami")
    assert resp.status_code == 200
    assert resp.text == "default"


def test_custom_user_id_from_header(client: TestClient) -> None:
    """X-User-Id header 应原样注入 request.state.user_id."""
    resp = client.get("/whoami", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    assert resp.text == "alice"


def test_empty_user_id_header(client: TestClient) -> None:
    """空 X-User-Id header 值应原样传递（非 default）。"""
    resp = client.get("/whoami", headers={"X-User-Id": ""})
    assert resp.status_code == 200
    assert resp.text == ""
