"""ProvenanceFactAssembler — assembles the complete set of
provenance-backed facts ApplyFlow may assert about one candidate.

Both generation flows (`GenerateTailoredResume`, `GenerateCoverLetter`)
need the identical corpus: the candidate's profile facts, each tagged with
the source the data model records for it, plus their remembered answers,
which are `ProvenanceSource.ANSWER` facts by construction (an
`AnswerMemory` can carry no other provenance — see that entity). Factoring
that into one application service keeps the two use cases from drifting
apart on the one question where drift would be dangerous: what counts as
evidence about a person.

Answers are included, not withheld, because a candidate who answered "I
led a team of five engineers" during gap resolution has *stated* that fact
as surely as if it were on their resume — refusing to draw on it would
throw away the whole point of remembering answers. They are, however, only
ever included as facts to validate against; nothing here decides what a
document says.
"""

from __future__ import annotations

from src.domain.exceptions import ProfileNotFoundError
from src.domain.repositories.answer_memory_repository import AnswerMemoryRepository
from src.domain.repositories.profile_repository import ProfileRepository
from src.domain.services.candidate_fact_extractor import CandidateFactExtractor
from src.domain.value_objects.provenance_backed_fact import ProvenanceBackedFact


class ProvenanceFactAssembler:
    """Builds one candidate's provenance-backed fact corpus."""

    def __init__(
        self,
        profile_repository: ProfileRepository,
        answer_memory_repository: AnswerMemoryRepository,
        fact_extractor: CandidateFactExtractor | None = None,
    ) -> None:
        self._profile_repository = profile_repository
        self._answer_memory_repository = answer_memory_repository
        self._fact_extractor = fact_extractor or CandidateFactExtractor()

    async def assemble(self, user_id: str) -> tuple[ProvenanceBackedFact, ...]:
        """Return every fact that may be asserted about `user_id`.

        Raises `ProfileNotFoundError` when the user has no profile: with no
        profile there is no provenance-backed record to generate from, and
        producing a document anyway would mean writing one out of nothing.
        """
        profile = await self._profile_repository.get_by_user_id(user_id)
        if profile is None:
            raise ProfileNotFoundError(user_id)

        facts = self._fact_extractor.extract_provenance_backed(profile)

        answer_memories = await self._answer_memory_repository.list_by_user_id(user_id)
        answer_facts = tuple(
            ProvenanceBackedFact(
                text=f"Asked '{memory.question_text}', answered: {memory.answer_text}",
                source=memory.source,
            )
            for memory in answer_memories
        )

        return facts + answer_facts
