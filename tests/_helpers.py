"""测试辅助工具."""

from unittest.mock import AsyncMock, MagicMock


def _mock_async_client() -> MagicMock:
    """创建支持 async with 的 mock 客户端."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client
