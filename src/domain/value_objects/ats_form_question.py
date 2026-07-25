"""AtsFormQuestion — everything the recognizer is allowed to read about one
field on an application form.

Why this exists next to `FormField`
-----------------------------------
`FormField` (in `application/ports/browser_automation_port.py`) is the
browser harness's description of a live control: it carries a handle, a
widget kind, the option list, the current value. The recognizer answers a
different question — "what is this field *asking*?" — and the answer must
not depend on any of that. So the domain takes only the four identifying
signals a portal exposes, and the application layer narrows a `FormField`
down to this shape before asking (see `AtsFormFieldPlanner`).

That is not layering ceremony. Keeping the recognizer's input this small is
what makes it a pure function over markup: it can be exercised with a
literal, it cannot accidentally start branching on a widget kind (which is
the filler's concern) or on a handle (which is the session's), and the
recognition rules for a platform can be written and reviewed without a
browser anywhere near them.

The four signals, in the order they are trusted:

1. `control_name` / `element_id` — the portal naming the field itself.
   `job_application[first_name]` is not a hint, it is a statement.
2. `autocomplete` — a machine-readable declaration in a standardized
   vocabulary, so it beats prose even though prose is more common.
3. `label` — what a human reads. Always present in some form, and where
   most real coverage comes from, but the least precise of the four.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AtsFormQuestion:
    """One field on an application form, reduced to what identifies it."""

    #: The best human-readable name for the field, already resolved from
    #: aria-label/`<label>`/placeholder by whoever read the form. May be
    #: empty when a portal labels a field purely visually.
    label: str
    #: The control's `name` attribute — `""` when it has none.
    control_name: str = ""
    #: The control's `id` attribute. Carried separately from `control_name`
    #: because single-page ATS forms routinely leave `name` empty and put
    #: the meaningful token on the id instead (Ashby's `_systemfield_*`).
    element_id: str = ""
    #: The raw `autocomplete` attribute, tokens and all
    #: (`"shipping address-line1"`), exactly as the page wrote it.
    autocomplete: str = ""
