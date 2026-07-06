"""LangChain implementation of the ResumeAnalyzerPort.

Wraps a raw LLM call behind the clean port interface defined in the
application layer. The use case has no idea LangChain or OpenAI exists.
"""

from __future__ import annotations

import json

from src.application.exceptions import ExternalServiceError
from src.application.ports.resume_analyzer_port import (
    ResumeAnalysisResult,
    ResumeAnalyzerPort,
)
from src.infrastructure.config import Settings

_SYSTEM_PROMPT = (
    "You are an expert career coach. Compare a candidate's resume to a job "
    "description. Return a JSON object with exactly two keys: "
    '"match_score" (an integer 0-100) and "cover_letter" (a concise, tailored '
    "cover letter, max 250 words). Return ONLY the JSON."
)


class LangChainResumeAnalyzer(ResumeAnalyzerPort):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._chain = self._build_chain()

    def _build_chain(self):
        # Imported lazily so the app can boot without LangChain installed in
        # non-LLM contexts (tests, migrations).
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=self._settings.llm_model,
            temperature=self._settings.llm_temperature,
            api_key=self._settings.openai_api_key,
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _SYSTEM_PROMPT),
                (
                    "human",
                    "JOB DESCRIPTION:\n{job_description}\n\nRESUME:\n{resume_text}",
                ),
            ]
        )
        return prompt | llm

    async def analyze(
        self, resume_text: str, job_description: str
    ) -> ResumeAnalysisResult:
        try:
            response = await self._chain.ainvoke(
                {"resume_text": resume_text, "job_description": job_description}
            )
            payload = json.loads(_extract_content(response))
            return ResumeAnalysisResult(
                match_score=int(payload["match_score"]),
                cover_letter=str(payload["cover_letter"]),
            )
        except Exception as exc:  # noqa: BLE001 - re-thrown as app-level error
            raise ExternalServiceError(
                f"Resume analysis failed: {exc}"
            ) from exc


def _extract_content(response: object) -> str:
    content = getattr(response, "content", response)
    return content if isinstance(content, str) else str(content)
