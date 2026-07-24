import pytest

from src.domain.entities.answer_memory import AnswerMemory
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.provenance_source import ProvenanceSource


def _answer_memory(**overrides) -> AnswerMemory:
    defaults: dict = dict(
        id="am-1",
        user_id="user-1",
        question_text="Are you willing to relocate?",
        answer_text="Yes, within the US.",
        embedding=[0.1, 0.2, 0.3],
        source=ProvenanceSource.ANSWER,
    )
    defaults.update(overrides)
    return AnswerMemory(**defaults)


def test_valid_answer_memory_constructs():
    memory = _answer_memory()
    assert memory.question_text == "Are you willing to relocate?"
    assert memory.embedding == [0.1, 0.2, 0.3]
    assert memory.source is ProvenanceSource.ANSWER


def test_empty_id_rejected():
    with pytest.raises(InvalidValueError):
        _answer_memory(id="")


def test_empty_user_id_rejected():
    with pytest.raises(InvalidValueError):
        _answer_memory(user_id="")


def test_blank_question_text_rejected():
    with pytest.raises(InvalidValueError):
        _answer_memory(question_text="   ")


def test_blank_answer_text_rejected():
    with pytest.raises(InvalidValueError):
        _answer_memory(answer_text="   ")


def test_empty_embedding_rejected():
    with pytest.raises(InvalidValueError):
        _answer_memory(embedding=[])


def test_non_numeric_embedding_rejected():
    with pytest.raises(InvalidValueError):
        _answer_memory(embedding=[0.1, "not-a-number", 0.3])


def test_raw_string_source_rejected():
    with pytest.raises(InvalidValueError):
        _answer_memory(source="answer")


@pytest.mark.parametrize(
    "other_source", [ProvenanceSource.PARSED_RESUME, ProvenanceSource.USER_ENTERED]
)
def test_only_answer_provenance_is_accepted(other_source):
    """An AnswerMemory only ever exists because a candidate answered a
    question directly — it can never be tagged with another provenance."""
    with pytest.raises(InvalidValueError):
        _answer_memory(source=other_source)


def test_sensitive_flag_is_set():
    assert AnswerMemory.SENSITIVE is True
