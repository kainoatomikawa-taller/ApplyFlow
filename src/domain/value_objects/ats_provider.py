"""AtsProvider — the applicant-tracking-system platforms ApplyFlow resolves
job listings against directly (see `identify_ats_board`), rather than
through a generic web search snippet.
"""

from __future__ import annotations

from enum import StrEnum


class AtsProvider(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
