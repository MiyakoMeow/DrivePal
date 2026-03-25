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
