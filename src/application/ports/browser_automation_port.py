"""BrowserAutomationPort — an outbound port for driving a real browser
over a role's application portal (the `apply_url` Epic 02 resolved).

Every autofill capability builds on this port, so its surface is
deliberately narrow: open a session on one apply URL, read the form's
fields, write a value into a named field, attach a file, take a
screenshot, close. There is no "run this selector", no "evaluate this
script", and no way to click an arbitrary element — a caller (eventually
an LLM-driven autofill use case) can only touch fields the harness itself
discovered and handed back.

That constraint is the point. Fields are addressed by an opaque `handle`
minted by `read_fields()`, never by a caller-supplied CSS/XPath selector,
which means:

- a caller cannot reach an element the harness chose not to expose
  (hidden inputs, disabled controls, submit buttons — notably, nothing
  here can submit an application),
- a caller cannot smuggle a selector engine expression into what looks
  like a field name, and
- a handle that no longer identifies the same field fails loudly
  (`StaleFormFieldError`) instead of quietly writing a candidate's phone
  number into someone else's question.

Handles are only valid for the most recent `read_fields()` snapshot on
that session. Any navigation invalidates them; so does the page mutating
underneath a snapshot. The remedy is always the same — call
`read_fields()` again — which is why one error type covers both cases.

Two things a session will not do
-------------------------------
`read_page_signals()` exists so a caller can find out what kind of page it
is actually on before touching it — specifically, whether the portal has a
hard boundary on it (a CAPTCHA, an e-signature, a sign-in wall). It returns
a `PortalPageSignals` reading for `HardStopDetector` to judge; the port
gathers facts and never decides.

And regardless of what any caller asks for, a field the domain's
`HumanOnlyFieldPolicy` recognizes as human-only — a password, a signature,
a challenge answer — is refused (`HumanOnlyFieldError`), which is what makes
"ApplyFlow never solves CAPTCHAs, creates accounts, or types passwords" a
property of this layer instead of a promise about the layers above it. Such
fields are still *reported* by `read_fields()`, carrying
`human_only_boundary`: hiding them would hide the very evidence that a
hand-off is needed.

Implementations own the browser entirely: launching it, isolating each
session from every other one, and tearing both down. Callers never see a
browser, a page, or a driver object.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from types import TracebackType

from src.domain.value_objects.hard_stop_kind import HardStopKind
from src.domain.value_objects.portal_page_signals import PortalPageSignals


class FormFieldKind(StrEnum):
    """What a discovered form field accepts, normalized away from HTML.

    Callers branch on this to decide *how* to supply a value, so it
    collapses the long tail of `<input type=...>` values into the shapes
    that actually differ in handling. `TEXT` is the fallback for any
    input type an implementation doesn't recognize — an unknown type is
    still almost always a text box.

    `PASSWORD` is split out from `TEXT` on purpose despite filling
    identically: nothing may ever write into one, and a distinct kind lets
    that be enforced by construction rather than by pattern-matching labels
    (see `HumanOnlyFieldPolicy`, and `FormField.human_only_boundary`).
    """

    TEXT = "text"
    PASSWORD = "password"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"
    NUMBER = "number"
    DATE = "date"
    TEXTAREA = "textarea"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    FILE = "file"


@dataclass(frozen=True)
class FormFieldOption:
    """One selectable choice on a `SELECT` field.

    Both halves are carried because they serve different callers: `label`
    is what a human (or a model reading the form) recognizes, `value` is
    what the portal actually submits, and on real ATS forms the two are
    routinely unrelated ("United States" vs. a UUID).
    """

    label: str
    value: str


@dataclass(frozen=True)
class FormField:
    """One fillable field on the currently loaded application form.

    This is a read-only description, not a live handle to the element:
    `handle` is what addresses the element, and it is only meaningful to
    the session that minted it.
    """

    #: Opaque address for this field, valid only for the snapshot that
    #: produced it and only on the session that minted it.
    handle: str
    kind: FormFieldKind
    #: Best available human-readable name for the field, resolved from
    #: (in order) aria-label, aria-labelledby, an associated or wrapping
    #: `<label>`, the placeholder, and finally the field's own name.
    #: May be empty when a portal labels a field purely visually.
    label: str
    #: The form control's `name` attribute (`""` when it has none).
    #: Radio buttons in one group share a name.
    name: str
    #: Whether the portal marks the field required. Only as trustworthy
    #: as the portal's markup — many ATS forms mark required fields
    #: visually and validate on submit without setting the attribute, so
    #: treat `False` as "not asserted", not "safe to leave blank".
    required: bool = False
    placeholder: str = ""
    #: The field's current value: the text in a text-like field, the
    #: selected option's `value` on a `SELECT`, or the value that would
    #: be submitted if checked on a `CHECKBOX`/`RADIO` (see `checked`).
    value: str = ""
    #: Whether a `CHECKBOX`/`RADIO` is currently checked. Always `False`
    #: for every other kind.
    checked: bool = False
    #: The choices on a `SELECT`, in the order the portal lists them.
    #: Empty for every other kind.
    options: tuple[FormFieldOption, ...] = ()
    #: The `maxlength` the portal enforces, when it declares one — worth
    #: honoring before writing long free text into a textarea.
    max_length: int | None = None
    #: Everything else the page said about this field, for callers that
    #: need to reason past the normalized shape above (`id`, `autocomplete`,
    #: the raw `input` type, …).
    attributes: dict[str, str] = field(default_factory=dict)
    #: Which hard boundary this field belongs to, when it is one only the
    #: candidate may fill — a password, a signature, a CAPTCHA answer — as
    #: judged by the domain's `HumanOnlyFieldPolicy` at discovery time.
    #: `None` for an ordinary question. A field with a boundary set is
    #: reported (a caller has to be able to see *why* a portal needs a
    #: hand-off) but can never be written to: `fill` and `attach_file`
    #: refuse it with `HumanOnlyFieldError`.
    human_only_boundary: HardStopKind | None = None

    @property
    def is_human_only(self) -> bool:
        return self.human_only_boundary is not None


class BrowserSessionPort(ABC):
    """One isolated browsing session parked on one application form.

    A session is stateful and single-use: it owns its own cookies and
    storage, shares nothing with any other session, and is finished once
    `close()` returns. Every method raises `BrowserSessionClosedError`
    after that.

    Sessions are async context managers, so the common case cannot leak
    one:

        async with await harness.open(apply_url) as session:
            fields = await session.read_fields()
    """

    @property
    @abstractmethod
    def current_url(self) -> str:
        """The URL actually loaded — which may differ from the one passed
        to `open()`, since portals routinely redirect an apply link."""

    @abstractmethod
    async def read_page_signals(self) -> PortalPageSignals:
        """Read what kind of page this is, without touching it.

        The reading a hard-boundary check runs on: the landed URL, what the
        page says, what it loads, how its markup is named, and what its form
        asks for — across the main document and every frame. Implementations
        collect and normalize; they never judge (that is
        `HardStopDetector`'s job, in the domain).

        Safe to call on any page, including one with no form at all: a page
        that presents nothing fillable still has a URL and text, and those
        are frequently the whole story (a portal that redirected an apply
        link to its login screen).

        Call this *before* `read_fields()` on an unfamiliar portal. Reading a
        boundary first is what lets a caller stop before it has touched
        anything.
        """

    @abstractmethod
    async def read_fields(self) -> tuple[FormField, ...]:
        """Snapshot every fillable field on the loaded form.

        Returns fields in document order, across the main document and
        any nested frames (ATS forms are frequently embedded in one).
        Only fields a caller could legitimately fill are included:
        hidden, disabled and read-only controls, buttons, and submit
        inputs are all left out.

        Calling this again re-snapshots the page and invalidates every
        handle from the previous call. An empty tuple means the page
        genuinely presented no fillable field within the implementation's
        wait budget — a login wall, a dead posting, or an interstitial —
        not an error.
        """

    @abstractmethod
    async def fill(self, handle: str, value: str) -> None:
        """Write `value` into the field addressed by `handle`.

        The interpretation of `value` follows the field's `kind`:

        - text-like kinds take it literally;
        - a `SELECT` matches it against an option's value or label —
          exactly, never a close-enough guess;
        - a `CHECKBOX` reads it as a boolean first ("no" unticks it), and
          falls back to treating its own label as "tick this";
        - a `RADIO` reads it as its own label/value first ("No" selects
          the No button), and otherwise accepts any true-ish value. A
          radio can never be cleared — choose another option instead.

        Raises `HumanOnlyFieldError` when the field is one only the candidate
        may fill (`human_only_boundary` is set) — checked before anything is
        typed, and not overridable, `RejectedFieldValueError` when the field
        cannot represent `value`, `FormFieldNotFillableError` when this
        operation doesn't apply to the field's kind (a `FILE` field — use
        `attach_file`) or the element refused to accept input, and
        `StaleFormFieldError` when `handle` no longer identifies the same
        field.
        """

    @abstractmethod
    async def attach_file(self, handle: str, *, filename: str, content: bytes) -> None:
        """Attach `content` to the `FILE` field addressed by `handle`.

        Takes bytes rather than a path so callers stay decoupled from
        wherever the bytes live (`FileStoragePort` today, object storage
        later) and so nothing in the application layer has to hold a
        filesystem path. `filename` is what the portal will record;
        implementations reduce it to a bare filename, since it crosses
        into a multipart upload.

        Refuses a human-only field (`HumanOnlyFieldError`) on the same terms
        as `fill` — an upload slot asking for a signed copy of something is
        no more automatable than a signature box.
        """

    @abstractmethod
    async def screenshot(self) -> bytes:
        """Capture the loaded page as PNG bytes.

        The verification primitive for everything built on top: proof of
        what a filled form actually looked like, for a human review step
        or for diagnosing a portal that didn't behave as read.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release this session and everything it holds. Idempotent, and
        safe to call on a session whose page already crashed."""

    async def __aenter__(self) -> BrowserSessionPort:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()


class BrowserAutomationPort(ABC):
    """Abstraction over a managed browser that hands out form sessions."""

    @abstractmethod
    async def open(self, url: str) -> BrowserSessionPort:
        """Open an isolated session and load the application form at `url`.

        Returns only once the page has loaded. Raises
        `BrowserNavigationError` if it never does — a timeout, a DNS or
        connection failure, or a portal answering with an error status —
        and leaks nothing when it does: a failed open leaves no session
        behind to clean up.
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """Close every session still open and release the browser itself.

        Idempotent. This is the backstop that guarantees no browser
        process outlives its owner even if individual sessions were
        dropped without being closed; a later `open()` is free to start a
        fresh browser.
        """
