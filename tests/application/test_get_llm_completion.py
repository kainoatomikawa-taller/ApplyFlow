"""GetLlmCompletion use case tests using an in-memory fake port.

Proves the application layer depends only on LlmClientPort, not on
Anthropic or any other provider SDK.
"""

import pytest

from src.application.dtos.llm_dtos import LlmCompletionInput
from src.application.ports.llm_client_port import LlmClientPort
from src.application.use_cases.get_llm_completion import GetLlmCompletion


class FakeLlmClient(LlmClientPort):
    def __init__(self, response: str = "pong") -> None:
        self.response = response
        self.calls: list[tuple[str, str | None]] = []

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        return self.response


@pytest.mark.asyncio
async def test_execute_returns_the_client_completion():
    client = FakeLlmClient(response="hello there")
    use_case = GetLlmCompletion(llm_client=client)

    output = await use_case.execute(LlmCompletionInput(prompt="hi"))

    assert output.text == "hello there"
    assert client.calls == [("hi", None)]


@pytest.mark.asyncio
async def test_execute_forwards_the_system_prompt():
    client = FakeLlmClient()
    use_case = GetLlmCompletion(llm_client=client)

    await use_case.execute(LlmCompletionInput(prompt="hi", system="be terse"))

    assert client.calls == [("hi", "be terse")]
