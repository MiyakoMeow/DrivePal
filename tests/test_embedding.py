"""EmbeddingModel 批量大小测试."""


def test_embedding_model_uses_batch_size():
    """EmbeddingModel 接受 batch_size 参数并存储"""
    from app.models.embedding import EmbeddingModel
    from app.models.settings import EmbeddingProviderConfig
    from app.models.types import ProviderConfig

    cfg = EmbeddingProviderConfig(
        provider=ProviderConfig(model="test", base_url="http://x", api_key="k")
    )
    model = EmbeddingModel(provider=cfg, batch_size=50)
    assert model.batch_size == 50


def test_embedding_model_default_batch_size():
    """默认 batch_size 为 32"""
    from app.models.embedding import EmbeddingModel
    from app.models.settings import EmbeddingProviderConfig
    from app.models.types import ProviderConfig

    cfg = EmbeddingProviderConfig(
        provider=ProviderConfig(model="test", base_url="http://x", api_key="k")
    )
    model = EmbeddingModel(provider=cfg)
    assert model.batch_size == 32
