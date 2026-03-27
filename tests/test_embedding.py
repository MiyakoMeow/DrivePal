from unittest.mock import Mock, patch
from app.models.embedding import EmbeddingModel


@patch("app.models.embedding.HuggingFaceBgeEmbeddings")
def test_embedding_model_init(mock_hf):
    mock_instance = Mock()
    mock_instance.embed_query.return_value = [0.1, 0.2, 0.3]
    mock_hf.return_value = mock_instance

    model = EmbeddingModel()
    assert model.model_name == "bge-small-zh-v1.5"


@patch("app.models.embedding.HuggingFaceBgeEmbeddings")
def test_encode(mock_hf):
    mock_instance = Mock()
    mock_instance.embed_query.return_value = [0.1, 0.2, 0.3]
    mock_hf.return_value = mock_instance

    model = EmbeddingModel()
    result = model.encode("测试文本")
    assert result == [0.1, 0.2, 0.3]


@patch("app.models.embedding.HuggingFaceBgeEmbeddings")
def test_encode_returns_list(mock_hf):
    """Test that encode returns a Python list, not numpy array."""
    import numpy as np

    mock_instance = Mock()
    mock_instance.embed_query.return_value = np.array([0.1, 0.2, 0.3])
    mock_hf.return_value = mock_instance

    model = EmbeddingModel()
    result = model.encode("test")
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert all(isinstance(x, (int, float)) for x in result)


@patch("app.models.embedding.HuggingFaceBgeEmbeddings")
def test_batch_encode_returns_list(mock_hf):
    """Test that batch_encode returns list of lists."""
    import numpy as np

    mock_instance = Mock()
    mock_instance.embed_documents.return_value = [
        np.array([0.1, 0.2]),
        np.array([0.3, 0.4]),
    ]
    mock_hf.return_value = mock_instance

    model = EmbeddingModel()
    result = model.batch_encode(["test1", "test2"])
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert all(isinstance(row, list) for row in result)
