from adapters.memory_adapters.keyword_adapter import KeywordAdapter
from adapters.memory_adapters.llm_only_adapter import LLMOnlyAdapter
from adapters.memory_adapters.embeddings_adapter import EmbeddingsAdapter
from adapters.memory_adapters.memory_bank_adapter import MemoryBankAdapter

ADAPTERS = {
    "keyword": KeywordAdapter,
    "llm_only": LLMOnlyAdapter,
    "embeddings": EmbeddingsAdapter,
    "memory_bank": MemoryBankAdapter,
}
