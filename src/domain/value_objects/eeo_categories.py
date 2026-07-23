"""EEO self-identification category enums.

Modeled after the categories on standard US EEO-1 / VEVRAA / Section 503
self-identification forms. Every enum includes an explicit
"decline to self-identify" member so choosing not to answer is always a
distinct, recorded choice — never silently inferred from a missing value.
"""

from __future__ import annotations

from enum import StrEnum


class GenderIdentity(StrEnum):
    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"
    DECLINE_TO_SELF_IDENTIFY = "decline_to_self_identify"


class RaceEthnicity(StrEnum):
    HISPANIC_OR_LATINO = "hispanic_or_latino"
    WHITE = "white"
    BLACK_OR_AFRICAN_AMERICAN = "black_or_african_american"
    NATIVE_HAWAIIAN_OR_PACIFIC_ISLANDER = "native_hawaiian_or_pacific_islander"
    ASIAN = "asian"
    AMERICAN_INDIAN_OR_ALASKA_NATIVE = "american_indian_or_alaska_native"
    TWO_OR_MORE_RACES = "two_or_more_races"
    DECLINE_TO_SELF_IDENTIFY = "decline_to_self_identify"


class VeteranStatus(StrEnum):
    PROTECTED_VETERAN = "protected_veteran"
    NOT_A_PROTECTED_VETERAN = "not_a_protected_veteran"
    DECLINE_TO_SELF_IDENTIFY = "decline_to_self_identify"


class DisabilityStatus(StrEnum):
    HAS_DISABILITY = "has_disability"
    NO_DISABILITY = "no_disability"
    DECLINE_TO_SELF_IDENTIFY = "decline_to_self_identify"
