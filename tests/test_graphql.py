"""GraphQL 端点测试."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from app.api.main import app

    return TestClient(app)


GRAPHQL_ENDPOINT = "/graphql"


def _graphql_query(
    client: TestClient, query: str, variables: dict | None = None
) -> dict:
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = client.post(GRAPHQL_ENDPOINT, json=payload)
    return resp.json()


def test_graphql_endpoint_responds(client: TestClient) -> None:
    result = _graphql_query(client, "{ __typename }")
    assert "data" in result


def test_experiment_report_query(client: TestClient) -> None:
    result = _graphql_query(client, "{ experimentReport { report } }")
    assert "data" in result
    assert result["data"]["experimentReport"]["report"] is not None


def test_scenario_presets_query(client: TestClient) -> None:
    result = _graphql_query(client, "{ scenarioPresets { id name } }")
    assert "data" in result
    assert isinstance(result["data"]["scenarioPresets"], list)


def test_save_scenario_preset(client: TestClient) -> None:
    result = _graphql_query(
        client,
        """
        mutation($name: String!, $ctx: DrivingContextInput!) {
            saveScenarioPreset(input: { name: $name, context: $ctx }) {
                id name
            }
        }
    """,
        {"name": "test-highway", "ctx": {"scenario": "highway"}},
    )
    assert "data" in result
    preset = result["data"]["saveScenarioPreset"]
    assert preset["name"] == "test-highway"
    assert preset["id"] != ""


def test_delete_scenario_preset(client: TestClient) -> None:
    result = _graphql_query(
        client,
        """
        mutation($name: String!, $ctx: DrivingContextInput!) {
            saveScenarioPreset(input: { name: $name, context: $ctx }) { id }
        }
    """,
        {"name": "to-delete", "ctx": {"scenario": "parked"}},
    )
    preset_id = result["data"]["saveScenarioPreset"]["id"]

    del_result = _graphql_query(
        client,
        """
        mutation($presetId: String!) { deleteScenarioPreset(presetId: $presetId) }
    """,
        {"presetId": preset_id},
    )
    assert del_result["data"]["deleteScenarioPreset"] is True


def test_delete_nonexistent_preset(client: TestClient) -> None:
    result = _graphql_query(
        client,
        """
        mutation { deleteScenarioPreset(presetId: "nonexistent") }
    """,
    )
    assert result["data"]["deleteScenarioPreset"] is False


def test_feedback_invalid_action(client: TestClient) -> None:
    result = _graphql_query(
        client,
        """
        mutation {
            submitFeedback(input: { eventId: "x", action: "invalid" }) {
                status
            }
        }
    """,
    )
    assert "errors" in result


def test_history_query(client: TestClient) -> None:
    result = _graphql_query(
        client,
        """
        query { history(limit: 5, memoryMode: MEMORY_BANK) { id content } }
    """,
    )
    assert "data" in result
    assert isinstance(result["data"]["history"], list)
