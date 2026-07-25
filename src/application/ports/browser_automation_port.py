"""BrowserAutomationPort — an outbound port for driving a real browser
over a role's application portal (the `apply_url` Epic 02 resolved).

Every autofill capability builds on this port, so its surface is
deliberately narrow: open a session on one apply URL, read the form's
fields, write a value into a named field, attach a file, observe what
else the page is showing, take a screenshot, close. There is no "run
this selector", no "evaluate this script", and no way to click an
arbitrary element — a caller (eventually an LLM-driven autofill use
case) can only touch fields the harness itself discovered and handed
back.

That constraint is the point. Fields are addressed by an opaque `handle`
minted by `read_fields()`, never by a caller-supplied CSS/XPath selector,
which means:

- a caller cannot reach an element the harness chose not to expose
  (hidden inputs, disabled controls, buttons of any kind),
- a caller cannot smuggle a selector engine expression into what looks
  like a field name, and
- a handle that no longer identifies the same field fails loudly
  (`StaleFormFieldError`) instead of quietly writing a candidate's phone
  number into someone else's question.

Handles are only valid for the most recent `read_fields()` snapshot on
that session. Any navigation invalidates them; so does the page mutating
underneath a snapshot. The remedy is always the same — call
`read_fields()` again — which is why one error type covers both cases.

Submitting is a separate capability, on purpose
-----------------------------------------------
An application has to be sendable, or ApplyFlow stops one step short of
the thing the candidate wanted. So `read_submit_controls()` /
`press_submit()` exist — and they are deliberately *not* reachable from
anything the filling path holds:

- `read_fields()` still discovers no button and no submit input, so no
  field handle can press anything. The two handle namespaces are
  separate and are looked up in separate snapshots; a field handle
  passed to `press_submit()` is refused, and vice versa.
- Pressing requires a caller to have asked for submit controls by name,
  chosen one, and named it. Nothing does that incidentally.
- The harness still decides nothing about *whether* to press. That gate
  — the candidate's explicit approval, their confirmation of every
  sensitive value, and the absence of any `ApplicationBoundary` — lives
  in the use case, which is where policy belongs.

The rule the whole epic rests on is unchanged in substance: nothing is
submitted unattended. It is now enforced one layer up, by a use case that
requires a human's instruction, rather than by the harness being
physically incapable.

`read_page_signals()` is the other addition: the observations the domain
needs to recognize a CAPTCHA, a signature request, or a login wall (see
`detect_application_boundaries`). It reports what is on the page and
interprets none of it — no rule about what counts as a challenge lives in
this port or in any implementation of it.

Implementations own the browser entirely: launching it, isolating each
session from every other one, and tearing both down. Callers never see a
browser, a page, or a driver object.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from types import TracebackType

from src.domain.value_objects.page_signals import PageSignals


class FormFieldKind(StrEnum):
    """What a discovered form field accepts, normalized away from HTML.

    Callers branch on this to decide *how* to supply a value, so it
    collapses the long tail of `<input type=...>` values into the shapes
    that actually differ in handling. `TEXT` is the fallback for any
    input type an implementation doesn't recognize — an unknown type is
    still almost always a text box.

    `PASSWORD` is split out from `TEXT` on purpose despite filling
    identically: an autofill layer must never invent a value for one, and
    a distinct kind lets it enforce that rather than pattern-match labels.
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


@dataclass(frozen=True)
class SubmitControl:
    """One control that would send the form if pressed.

    Carried separately from `FormField` and minted by a separate call, so
    that holding a form field can never be a way to press something. The
    `label` is what the button says — "Submit application", "Send" — and
    is what a review screen shows the candidate before they authorize the
    press, because "press the button" is not informed consent when the
    page has three of them.
    """

    #: Opaque address for this control, valid only for the snapshot that
    #: produced it and only on the session that minted it. Not
    #: interchangeable with a `FormField.handle`.
    handle: str
    label: str


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

        Raises `RejectedFieldValueError` when the field cannot represent
        `value`, `FormFieldNotFillableError` when this operation doesn't
        apply to the field's kind (a `FILE` field — use `attach_file`) or
        the element refused to accept input, and `StaleFormFieldError`
        when `handle` no longer identifies the same field.
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
        """

    @abstractmethod
    async def read_page_signals(self) -> PageSignals:
        """Observe what the loaded page is showing, beyond its fields.

        Everything a caller needs to recognize a human-only check —
        embedded frame and script URLs, markup tokens, the visible text —
        gathered across the main document and every nested frame, exactly
        like `read_fields()`. The observation is *uninterpreted*: which
        markers mean a CAPTCHA and which phrases mean a signature request
        are domain rules (`detect_application_boundaries`), and an
        implementation of this port must contain none of them.

        Cheap enough to call alongside every form read, and it mints no
        handles, so calling it never invalidates a snapshot.
        """

    @abstractmethod
    async def read_submit_controls(self) -> tuple[SubmitControl, ...]:
        """Snapshot the controls that would send this form, in page order.

        Only controls that actually submit: `<button type=submit>`, a
        button with no type inside a form (which HTML makes a submit
        button), `<input type=submit|image>`. A "Save draft" or "Add
        another employer" button is not one of these and is never
        returned — the only thing this call can hand back is a way to send
        the application.

        Empty is a legitimate answer, and an important one: a portal that
        submits through script from a plain `<button type=button>` leaves
        nothing here to press, and the honest response is to tell the
        candidate to finish in their own browser rather than to start
        clicking things that look like buttons.

        Handles minted here live in their own snapshot; they are not
        `FormField` handles and cannot be used as one.
        """

    @abstractmethod
    async def press_submit(self, handle: str) -> None:
        """Press the submit control addressed by `handle` and wait for the
        portal to respond.

        This sends the application. Implementations verify the control is
        still the one that was snapshotted (the same signature check every
        field write does) before pressing, because pressing whatever
        drifted into that position on a live page is not a mistake that
        can be taken back.

        Returns once the resulting navigation or in-page update has
        settled, so the caller can read the page it landed on. Raises
        `StaleFormFieldError` when `handle` is not a live submit-control
        handle for this session — including when it is a `FormField`
        handle — and `SubmitControlNotPressableError` when the control was
        found but would not accept the press.
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
