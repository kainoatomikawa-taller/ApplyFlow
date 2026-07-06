"""ResumeAnalyzerPort — an outbound port for AI-powered resume analysis.

The application layer defines this abstraction. The infrastructure layer
implements it with LangChain / an LLM provider. The use case never knows
which model is being used.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ResumeAnalysisResult:
    """Result returned by the resume analyzer."""

    match_score: int  # 0..100
    cover_letter: str


class ResumeAnalyzerPort(ABC):
    """Abstraction over an LLM-driven resume/job matcher."""

    @abstractmethod
    async def analyze(
        self, resume_text: str, job_description: str
    ) -> ResumeAnalysisResult:
        """Score a resume against a job description and draft a cover letter."""
