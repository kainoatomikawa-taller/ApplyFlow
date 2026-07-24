"""FeedbackRating value object — a candidate's thumbs-up/down reaction to
a ranked job match."""

from __future__ import annotations

from enum import StrEnum


class FeedbackRating(StrEnum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
