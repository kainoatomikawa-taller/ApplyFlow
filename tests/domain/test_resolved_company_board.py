import pytest

from src.domain.entities.resolved_company_board import ResolvedCompanyBoard
from src.domain.exceptions import InvalidValueError
from src.domain.value_objects.ats_provider import AtsProvider


def _resolved_company_board(
    *,
    company: str = "Acme Corp",
    provider: AtsProvider = AtsProvider.GREENHOUSE,
    board_token: str = "acme",
    **kwargs,
) -> ResolvedCompanyBoard:
    return ResolvedCompanyBoard(
        company=company, provider=provider, board_token=board_token, **kwargs
    )


def test_valid_resolved_company_board_constructs():
    board = _resolved_company_board()
    assert board.company == "Acme Corp"
    assert board.provider == AtsProvider.GREENHOUSE
    assert board.board_token == "acme"


def test_normalized_company_is_derived():
    board = _resolved_company_board(company="  Acme  Corp  ")
    assert board.normalized_company == "acme corp"


def test_empty_company_rejected():
    with pytest.raises(InvalidValueError):
        _resolved_company_board(company="   ")


def test_empty_board_token_rejected():
    with pytest.raises(InvalidValueError):
        _resolved_company_board(board_token="")
