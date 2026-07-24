import pytest

from src.domain.services.job_title_matching import titles_match


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Backend Engineer", "Backend Engineer"),
        ("backend engineer", "  Backend   Engineer  "),
        ("Backend Engineer", "Backend Engineer, Platform"),
        ("Senior Backend Engineer, Platform", "Backend Engineer"),
    ],
)
def test_matching_titles(a: str, b: str):
    assert titles_match(a, b) is True


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Backend Engineer", "Frontend Engineer"),
        ("Backend Engineer", ""),
        ("", "Backend Engineer"),
        ("", ""),
    ],
)
def test_non_matching_titles(a: str, b: str):
    assert titles_match(a, b) is False
