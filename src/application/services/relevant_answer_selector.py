"""RelevantAnswerSelector — picks which of a candidate's remembered answers
are worth drawing on for one specific job.

Answers gathered during gap resolution are the most valuable material a
generated document has: they are the candidate's own words about experience
their resume never captured. But a candidate accumulates answers across every
application they make, and a letter about a platform engineering role has no
use for what they said about retail hours. Handing the whole pile to a model
buries the two or three answers that matter, so this selects them.

Selection is semantic, using the embedding every `AnswerMemory` already
carries (that is what "embedding-indexed" bought us) and the same
`AnswerSimilarityMatcher` that recognizes an already-answered question —
against `DEFAULT_RELEVANCE_THRESHOLD` rather than the strict re-ask bar, since
the question here is "related to what this job asked about", not "identical
to it". One embedding call per selection, for the job's own words.

This narrows a *prompt*, never the guard's corpus
-------------------------------------------------
What comes back is a subset for the generator to foreground. The provenance
guard must keep validating against every attested fact
(`ProvenanceFactAssembler.assemble`), because narrowing what the guard can
see would strip true claims for the crime of being about something else —
the guard's job is to catch fabrication, not off-topic honesty. Selection
changes what gets *emphasized*; it can never change what is *permitted*.
"""

from __future__ import annotations

from src.application.ports.embedding_client_port import EmbeddingClientPort
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.services.answer_similarity_matcher import AnswerSimilarityMatcher
from src.domain.value_objects.provenance_backed_fact import ProvenanceBackedFact

#: How many remembered answers one document may foreground. A cover letter
#: has room to draw on a few of the candidate's own statements; past that
#: they crowd out the profile facts they sit beside.
DEFAULT_LIMIT = 3


class RelevantAnswerSelector:
    """Selects the remembered answers most relevant to a job."""

    def __init__(
        self,
        answer_memory_repository: AnswerMemoryRepository,
        embedding_client: EmbeddingClientPort,
        matcher: AnswerSimilarityMatcher | None = None,
    ) -> None:
        self._answer_memory_repository = answer_memory_repository
        self._embedding_client = embedding_client
        self._matcher = matcher or AnswerSimilarityMatcher()

    async def select(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = DEFAULT_LIMIT,
        threshold: float | None = None,
    ) -> tuple[ProvenanceBackedFact, ...]:
        """Return up to `limit` of `user_id`'s remembered answers related to
        `query` (the job's own words), most relevant first.

        Returns empty when the candidate has no answers on file or none
        clear the relevance bar — "nothing especially relevant" is a normal
        outcome, not a failure, and the document is still written from the
        full fact corpus either way. No answers means no embedding call:
        there would be nothing to compare against.
        """
        answers = await self._answer_memory_repository.list_by_user_id(user_id)
        if not answers or limit <= 0:
            return ()

        query_embedding = await self._embedding_client.embed(query)
        matches = self._matcher.find_matches(
            query_embedding,
            answers,
            threshold=(
                self._matcher.DEFAULT_RELEVANCE_THRESHOLD
                if threshold is None
                else threshold
            ),
            limit=limit,
        )
        return tuple(
            match.answer_memory.as_provenance_backed_fact() for match in matches
        )
