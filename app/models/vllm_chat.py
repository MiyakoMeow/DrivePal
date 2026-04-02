"""基于本地vLLM引擎的聊天模型."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import TYPE_CHECKING

from transformers import AutoTokenizer  # ty: ignore[possibly-missing-import]
from vllm import AsyncEngineArgs, AsyncLLMEngine, SamplingParams

from app.models.protocol import ChatModelProtocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _probe_engine(engine: AsyncLLMEngine, tokenizer: AutoTokenizer) -> bool:
    """探测引擎是否就绪."""
    messages = [{"role": "user", "content": "hi"}]
    prompt_text: str = tokenizer.apply_chat_template(  # ty: ignore[unresolved-attribute]
        messages, add_generation_prompt=True, tokenize=False
    )
    params = SamplingParams(temperature=0.0, max_tokens=1)
    request_id = "__availability_probe__"
    final_text = ""
    async for output in engine.generate(prompt_text, params, request_id):
        final_text = output.outputs[0].text
    return len(final_text) >= 0


def _wait_for_engine(
    engine: AsyncLLMEngine, tokenizer: AutoTokenizer, timeout: float
) -> bool:
    """在独立线程中等待引擎就绪."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, _probe_engine(engine, tokenizer))
        try:
            return bool(future.result(timeout=timeout))
        except Exception:
            return False


class VLLMChatModel(ChatModelProtocol):
    """基于本地vLLM引擎的聊天模型封装."""

    def __init__(
        self,
        model_id: str,
        temperature: float = 0.7,
        tensor_parallel_size: int = 1,
        max_model_len: int = 4096,
        availability_timeout: float = 120.0,
    ) -> None:
        """初始化vLLM引擎和tokenizer."""
        self.model_id = model_id
        self.temperature = temperature
        self.availability_timeout = availability_timeout
        self._request_counter = 0

        self._tokenizer = AutoTokenizer.from_pretrained(
            model_id, trust_remote_code=True
        )

        engine_args = AsyncEngineArgs(
            model=model_id,
            tensor_parallel_size=tensor_parallel_size,
            max_model_len=max_model_len,
            trust_remote_code=True,
        )
        self._engine = AsyncLLMEngine.from_engine_args(engine_args)

    def _next_request_id(self) -> str:
        self._request_counter += 1
        return f"vllm-request-{self._request_counter}"

    def _build_prompt(self, prompt: str, system_prompt: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return str(
            self._tokenizer.apply_chat_template(  # ty: ignore[unresolved-attribute]
                messages, add_generation_prompt=True, tokenize=False
            )
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        """生成回复."""
        prompt_text = self._build_prompt(prompt, system_prompt)
        params = SamplingParams(temperature=self.temperature, max_tokens=512)
        request_id = self._next_request_id()
        final_text = ""
        async for output in self._engine.generate(prompt_text, params, request_id):
            final_text = output.outputs[0].text
        return final_text

    async def generate_stream(  # ty: ignore[invalid-method-override]
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """流式生成回复."""
        prompt_text = self._build_prompt(prompt, system_prompt)
        params = SamplingParams(temperature=self.temperature, max_tokens=512)
        request_id = self._next_request_id()
        prev_len = 0
        async for output in self._engine.generate(prompt_text, params, request_id):
            current_text = output.outputs[0].text
            delta = current_text[prev_len:]
            if delta:
                yield delta
            prev_len = len(current_text)

    async def batch_generate(
        self,
        prompts: list[str],
        system_prompt: str | None = None,
    ) -> list[str]:
        """批量生成回复."""
        return [await self.generate(p, system_prompt) for p in prompts]

    def is_available(self) -> bool:
        """检查模型是否可用."""
        try:
            return _wait_for_engine(
                self._engine, self._tokenizer, self.availability_timeout
            )
        except Exception:
            return False
