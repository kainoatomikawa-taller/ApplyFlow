"""How a caller's string value maps onto an HTML form control.

These are HTML semantics, not business rules: "does this string mean the
checkbox should be ticked" and "which `<option>` did the caller mean" are
questions about the markup a portal served, so they live in
infrastructure alongside the browser that has to answer them.

The governing rule for both is **exact or nothing**. Matching is
normalized for case and whitespace, because a portal writing
`"United States "` and a caller writing `"United States"` mean the same
thing — but never fuzzy, prefix, or nearest-neighbor. On a job
application, an option picked because it *resembled* what was asked for is
a wrong answer submitted under the candidate's name; refusing and handing
back the list of options a field accepts is strictly better, and is what
`RejectedFieldValueError` exists to do.
"""

from __future__ import annotations

from src.application.ports.browser_automation_port import FormFieldOption

_TRUE_VALUES = frozenset({"true", "yes", "y", "1", "on", "checked", "x"})
_FALSE_VALUES = frozenset({"false", "no", "n", "0", "off", "unchecked", ""})


def normalize(value: str) -> str:
    """Casefold and collapse whitespace for comparison purposes only —
    never for the value actually written into a field."""
    return " ".join(value.split()).casefold()


def interpret_boolean(value: str) -> bool | None:
    """Read `value` as a tick/untick instruction, or `None` if it isn't one.

    `None` is a real outcome, not a failure to try: a caller that sent
    "United States" to a checkbox may have meant "tick the United States
    box", which is a different question answered by the option's own value
    (see `matches_own_value`).
    """
    normalized = normalize(value)
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def matches_own_value(*, value: str, own_value: str, label: str) -> bool:
    """Whether `value` names this checkbox/radio itself.

    Lets a caller tick the "Yes" radio in a Yes/No group by sending
    `"Yes"` — the option's label — rather than having to know that the
    harness would also have accepted the boolean `"true"`.
    """
    normalized = normalize(value)
    if not normalized:
        return False
    return normalized in {normalize(own_value), normalize(label)}


def match_option(
    options: tuple[FormFieldOption, ...], value: str
) -> FormFieldOption | None:
    """Find the single option `value` unambiguously names, or `None`.

    Exact `value` matches win over exact `label` matches, which win over
    normalized matches on either. That ordering matters when a portal's
    option values and labels overlap: an exact hit on what the form
    actually submits is the least ambiguous reading of the caller's intent.
    """
    for option in options:
        if option.value == value:
            return option
    for option in options:
        if option.label == value:
            return option
    normalized = normalize(value)
    for option in options:
        if normalized in {normalize(option.value), normalize(option.label)}:
            return option
    return None


def describe_options(options: tuple[FormFieldOption, ...]) -> str:
    """Render a field's accepted options for an error message, so a
    rejected value comes back with what would have worked."""
    if not options:
        return "no options"
    return ", ".join(
        f"'{option.label}'" if option.label else f"'{option.value}'"
        for option in options
    )
