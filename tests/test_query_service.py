"""测试: QueryService。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.query_service import QueryService


@pytest.mark.asyncio
async def test_process_delegates_to_workflow():
    """process_query 委托给 AgentWorkflow。"""
    mm = MagicMock()
    svc = QueryService(mm)
    with patch("app.services.query_service.AgentWorkflow") as mock_wf:
        wf_instance = MagicMock()
        wf_instance.run_with_stages = AsyncMock(
            return_value=("result", "evt_123", MagicMock()),
        )
        mock_wf.return_value = wf_instance

        result = await svc.process(
            query="加油",
            context_dict={"scenario": "parked"},
            mode="memory_bank",
        )
        assert result.result == "result"
        assert result.event_id == "evt_123"
        mock_wf.assert_called_once()
