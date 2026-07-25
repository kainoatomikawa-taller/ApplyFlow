"""PlaywrightBrowserAutomation — BrowserAutomationPort backed by a real
Chromium driven through Playwright.

## What owns what

One harness owns one browser process, launched lazily on the first
`open()` and shared by every session after it — a browser launch is the
expensive part (hundreds of milliseconds and a process), a
`BrowserContext` is not. Each session therefore gets its own context, so
two sessions never share cookies, storage, or a login: one candidate's
authenticated portal session cannot bleed into another's, and a portal
that sets a tracking cookie during one application does not carry it into
the next.

## Cleanup

Three layers, because a browser process outliving its owner is the failure
mode that takes a worker down:

1. `session.close()` disposes that session's context (and its pages), and
   is idempotent — closing twice, or closing a session whose page already
   crashed, is not an error.
2. Sessions are async context managers, so the ordinary call site cannot
   leak one even when the body raises.
3. `shutdown()` closes every session still registered, then the browser,
   then the driver. It is the backstop for sessions that were dropped
   rather than closed, and it is idempotent too — a later `open()` simply
   launches a fresh browser.

A navigation that fails is cleaned up before the exception leaves `open()`,
so a caller that never received a session has nothing to close.

## Failure handling

Everything Playwright raises is translated at this boundary into the
`BrowserAutomationError` family (per the infrastructure contract: no
`playwright.*` type escapes into the layers above). Navigation retries
once by default with exponential backoff, since a browser page load has
far more transient failure modes than an API call — but only for timeouts,
connection failures, 5xx, and 429. Any other 4xx means the portal
answered, so retrying it just wastes the budget.

## The boundary this layer will not cross

Every write first consults the boundary the domain assigned to the field at
discovery time (`FormField.human_only_boundary`), and refuses if there is one.
That is why "ApplyFlow never solves CAPTCHAs, creates accounts, or enters
passwords" is a property of the system rather than a convention: the refusal
lives at the only layer that can produce a keystroke, so no use case — and no
model driving one — can route around it. `read_page_signals()` is the other
half, the pre-touch reading that lets a caller recognize such a portal and
hand off before it has filled anything.

## The one deliberate cost

Every field interaction re-derives the element's signature and compares it
to the snapshot before touching it. That is an extra round trip per fill.
It buys the guarantee that matters most here: writing the right value into
the *wrong field* of a real job application is silent, unrecoverable, and
seen by a human reviewer at the company. A stale handle fails loudly
instead.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from mimetypes import guess_type
from pathlib import PurePosixPath
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    FilePayload,
    Frame,
    Locator,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from src.application.exceptions import (
    BrowserAutomationError,
    BrowserNavigationError,
    BrowserSessionClosedError,
    FormFieldNotFillableError,
    HumanOnlyFieldError,
    RejectedFieldValueError,
    StaleFormFieldError,
    SubmitControlNotPressableError,
)
from src.application.ports.browser_automation_port import (
    BrowserAutomationPort,
    BrowserSessionPort,
    FormField,
    FormFieldKind,
    SubmitControl,
)
from src.domain.value_objects.page_signals import PageSignals
from src.domain.value_objects.portal_page_signals import PortalPageSignals
from src.infrastructure.browser_automation.field_discovery import (
    FIELD_DISCOVERY_JS,
    FIELD_SELECTOR,
    FIELD_SIGNATURE_JS,
    to_form_field,
)
from src.infrastructure.browser_automation.field_values import (
    describe_options,
    interpret_boolean,
    match_option,
    matches_own_value,
)
from src.infrastructure.browser_automation.page_observation import (
    BOUNDARY_SIGNALS_JS,
    SUBMIT_DISCOVERY_JS,
    SUBMIT_SELECTOR,
    SUBMIT_SIGNATURE_JS,
    build_page_signals,
    to_submit_control,
)
from src.infrastructure.browser_automation.page_signals import (
    PAGE_SIGNALS_JS,
    to_page_signals,
)
from src.infrastructure.config import Settings

logger = logging.getLogger(__name__)

#: Statuses worth a second navigation attempt. Everything else in the 4xx
#: range is the portal answering definitively, not failing transiently.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

#: How often `read_fields` re-checks a page that has shown no field yet.
_FIELD_POLL_INTERVAL_SECONDS = 0.25

#: What a caller may send to tick or untick a checkbox, for error messages.
_BOOLEAN_HELP = "'yes'/'no', 'true'/'false', '1'/'0', or the field's own label"

#: Kinds `fill()` writes text into verbatim.
_TEXTUAL_KINDS = frozenset(
    {
        FormFieldKind.TEXT,
        FormFieldKind.PASSWORD,
        FormFieldKind.EMAIL,
        FormFieldKind.PHONE,
        FormFieldKind.URL,
        FormFieldKind.NUMBER,
        FormFieldKind.DATE,
        FormFieldKind.TEXTAREA,
    }
)


@dataclass(frozen=True)
class _SnapshotEntry:
    """A field from the latest snapshot plus everything needed to reach it
    again: the frame it lives in, its index in that frame's
    `FIELD_SELECTOR` enumeration, and the signature that proves the
    element still at that index is the same one."""

    field: FormField
    frame: Frame
    index: int
    signature: str


@dataclass(frozen=True)
class _SubmitEntry:
    """A submit control from the latest submit snapshot, plus how to reach
    it again. Kept in its own snapshot from `_SnapshotEntry`, so a form
    field handle can never resolve to something pressable."""

    control: SubmitControl
    frame: Frame
    index: int
    signature: str


class PlaywrightBrowserSession(BrowserSessionPort):
    """One browser context parked on one application form."""

    def __init__(
        self,
        *,
        page: Page,
        context: BrowserContext,
        settings: Settings,
        on_closed: Callable[[PlaywrightBrowserSession], None] | None = None,
    ) -> None:
        self._page = page
        self._context = context
        self._settings = settings
        self._on_closed = on_closed
        self._snapshot: dict[str, _SnapshotEntry] = {}
        #: Submit controls live in their own snapshot with their own handle
        #: prefix. Two dictionaries rather than one is the mechanism behind
        #: "a field handle cannot press anything": there is no lookup that
        #: can find a button from a handle `read_fields()` minted.
        self._submit_snapshot: dict[str, _SubmitEntry] = {}
        #: Bumped on every snapshot and baked into each handle, so a handle
        #: minted by an earlier `read_fields()` is rejected outright rather
        #: than resolving against whatever now sits at its old index.
        self._generation = 0
        self._closed = False

    @property
    def current_url(self) -> str:
        self._require_open()
        return self._page.url

    async def read_page_signals(self) -> PortalPageSignals:
        self._require_open()
        # Waits on the same budget as `read_fields`, and for the same reason
        # with higher stakes: a boundary check that ran before the form
        # mounted would read a blank page as a clean one, and a clean reading
        # is the only thing that lets anything above start filling. The
        # page-level pass runs *after* the wait so its text and markup
        # describe the page the form actually landed on.
        entries = await self._await_fields()
        readings: list[dict[str, Any]] = []
        for frame_index, frame in enumerate(self._page.frames):
            try:
                reading = await frame.evaluate(PAGE_SIGNALS_JS)
            except PlaywrightError as exc:
                # A frame detaching or navigating mid-read is ordinary on a
                # live page; what it was showing simply isn't in this reading.
                logger.debug(
                    "Skipped frame %d during signal collection: %s", frame_index, exc
                )
                continue
            if isinstance(reading, dict):
                readings.append(reading)

        return to_page_signals(
            url=self._page.url,
            frame_urls=[frame.url for frame in self._page.frames],
            frame_readings=readings,
            field_entries=[raw for _, _, _, raw in entries],
        )

    async def read_fields(self) -> tuple[FormField, ...]:
        self._require_open()
        entries = await self._await_fields()

        self._generation += 1
        snapshot: dict[str, _SnapshotEntry] = {}
        fields: list[FormField] = []
        for frame_index, index, frame, raw in entries:
            handle = f"g{self._generation}-f{frame_index}-{index}"
            field = to_form_field(handle, raw)
            snapshot[handle] = _SnapshotEntry(
                field=field,
                frame=frame,
                index=index,
                signature=str(raw.get("signature", "")),
            )
            fields.append(field)
        self._snapshot = snapshot
        return tuple(fields)

    async def fill(self, handle: str, value: str) -> None:
        entry = self._entry(handle)
        field = entry.field
        # Before the kind, before the element is even located: the one rule
        # with no exception path. Nothing gets typed into a credential, a
        # signature, or a challenge answer, whatever the caller believes it
        # is doing (see `_refuse_if_human_only`).
        self._refuse_if_human_only(field)
        # Kind is checked before the element is located: a caller who
        # reached for the wrong operation should be told exactly that,
        # rather than getting whatever the page happened to do next.
        if field.kind is FormFieldKind.FILE:
            raise FormFieldNotFillableError(
                handle, "it is a file input — use attach_file() instead"
            )
        if field.kind not in _TEXTUAL_KINDS and field.kind not in (
            FormFieldKind.SELECT,
            FormFieldKind.CHECKBOX,
            FormFieldKind.RADIO,
        ):  # pragma: no cover - defensive; every kind above is handled
            raise FormFieldNotFillableError(
                handle, f"fields of kind '{field.kind}' cannot be filled"
            )

        locator = await self._locate(entry)
        if field.kind is FormFieldKind.SELECT:
            await self._select(handle, locator, field, value)
            return
        if field.kind in (FormFieldKind.CHECKBOX, FormFieldKind.RADIO):
            await self._set_checked(handle, locator, field, value)
            return
        try:
            await locator.fill(value)
        except PlaywrightError as exc:
            raise self._translate_write_failure(handle, value, field, exc) from exc

    async def attach_file(self, handle: str, *, filename: str, content: bytes) -> None:
        entry = self._entry(handle)
        # Same first check as `fill`: an upload slot asking for a signed copy
        # of something is no more automatable than a signature box.
        self._refuse_if_human_only(entry.field)
        if entry.field.kind is not FormFieldKind.FILE:
            raise FormFieldNotFillableError(
                handle,
                f"it is a '{entry.field.kind}' field, not a file input — "
                "use fill() instead",
            )
        # The name crosses into a multipart upload, so it is reduced to a
        # bare filename: a caller-supplied "../../etc/passwd" must reach
        # the portal as "passwd", never as a path. `.name` yields ".." for
        # a path that is nothing but traversal, which is not a filename
        # either, so both relative markers are refused outright.
        safe_name = PurePosixPath(filename.replace("\\", "/")).name.strip()
        if not safe_name or safe_name in {".", ".."}:
            raise RejectedFieldValueError(
                handle, filename, "a non-empty filename with no path separators"
            )
        payload = FilePayload(
            name=safe_name,
            mimeType=guess_type(safe_name)[0] or "application/octet-stream",
            buffer=content,
        )
        locator = await self._locate(entry)
        try:
            await locator.set_input_files(payload)
        except PlaywrightError as exc:
            raise FormFieldNotFillableError(
                handle, f"the portal refused the upload: {_first_line(exc)}"
            ) from exc

    async def read_boundary_signals(self) -> PageSignals:
        self._require_open()
        payloads: list[dict[str, Any]] = []
        frame_urls: list[str] = []
        for index, frame in enumerate(self._page.frames):
            # The main frame's URL is reported as the page URL, not as an
            # embedded resource: "this page is a sign-in page" and "this
            # page embeds a challenge from elsewhere" are different
            # findings, and merging them would let a posting whose own URL
            # happens to contain a marker word read as a challenge.
            if frame is not self._page.main_frame and frame.url:
                frame_urls.append(frame.url)
            try:
                payload = await frame.evaluate(BOUNDARY_SIGNALS_JS)
            except PlaywrightError as exc:
                # Same as field discovery: a frame detaching mid-read is
                # ordinary on a live page, and what it held is simply not
                # part of this observation.
                logger.debug("Skipped frame %d while observing page: %s", index, exc)
                continue
            if isinstance(payload, dict):
                payloads.append(payload)

        return build_page_signals(
            url=self._page.url,
            frame_urls=tuple(frame_urls),
            frame_payloads=tuple(payloads),
        )

    async def read_submit_controls(self) -> tuple[SubmitControl, ...]:
        self._require_open()
        found: list[tuple[int, int, Frame, dict[str, Any]]] = []
        for frame_index, frame in enumerate(self._page.frames):
            try:
                raw_controls = await frame.evaluate(SUBMIT_DISCOVERY_JS)
            except PlaywrightError as exc:
                logger.debug(
                    "Skipped frame %d during submit discovery: %s", frame_index, exc
                )
                continue
            if not isinstance(raw_controls, list):  # pragma: no cover - defensive
                continue
            for raw in raw_controls:
                if not isinstance(raw, dict):  # pragma: no cover - defensive
                    continue
                index = raw.get("index")
                if not isinstance(index, int):  # pragma: no cover - defensive
                    continue
                found.append((frame_index, index, frame, raw))

        self._generation += 1
        snapshot: dict[str, _SubmitEntry] = {}
        controls: list[SubmitControl] = []
        for frame_index, index, frame, raw in found:
            handle = f"s{self._generation}-f{frame_index}-{index}"
            control = to_submit_control(handle, raw)
            snapshot[handle] = _SubmitEntry(
                control=control,
                frame=frame,
                index=index,
                signature=str(raw.get("signature", "")),
            )
            controls.append(control)
        self._submit_snapshot = snapshot
        return tuple(controls)

    async def press_submit(self, handle: str) -> None:
        self._require_open()
        entry = self._submit_snapshot.get(handle)
        if entry is None:
            # Covers the accident that matters most: a `FormField` handle
            # passed here. Field handles are never in this snapshot, so
            # they fail before anything is pressed.
            raise StaleFormFieldError(
                handle,
                "it is not part of this session's current submit-control snapshot",
            )

        locator = entry.frame.locator(SUBMIT_SELECTOR).nth(entry.index)
        try:
            signature = await locator.evaluate(SUBMIT_SIGNATURE_JS)
        except PlaywrightError as exc:
            raise StaleFormFieldError(handle, _first_line(exc)) from exc
        if signature != entry.signature:
            raise StaleFormFieldError(
                handle,
                "the page changed and a different control is now in its place",
            )

        try:
            await locator.click()
        except PlaywrightTimeoutError as exc:
            raise SubmitControlNotPressableError(
                handle,
                "it did not become clickable in time (it may be obscured by "
                f"a banner or overlay): {_first_line(exc)}",
            ) from exc
        except PlaywrightError as exc:
            raise SubmitControlNotPressableError(handle, _first_line(exc)) from exc

        # Every handle on both sides is now suspect: the press either
        # navigated or rewrote the form in place. Dropped rather than left
        # to fail one at a time, so the next call says "re-read" instead of
        # resolving against a page that no longer exists.
        self._snapshot = {}
        self._submit_snapshot = {}
        await self._settle()

    async def screenshot(self) -> bytes:
        self._require_open()
        try:
            return await self._page.screenshot(full_page=True)
        except PlaywrightError as exc:
            raise BrowserAutomationError(
                f"Could not capture the page at {self._page.url}: {_first_line(exc)}"
            ) from exc

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._snapshot = {}
        self._submit_snapshot = {}
        # Closing the context disposes its pages too. A context whose
        # browser already died raises here, and that is not a failure to
        # report: the resource this call exists to release is already gone.
        try:
            await self._context.close()
        except PlaywrightError as exc:
            logger.debug("Browser context was already gone on close: %s", exc)
        if self._on_closed is not None:
            self._on_closed(self)

    # -- internals ---------------------------------------------------------

    async def _await_fields(self) -> list[tuple[int, int, Frame, dict[str, Any]]]:
        """Run the discovery pass, re-checking a page that has shown no field
        yet until the wait budget is spent.

        A form that mounts after first paint is the norm on modern ATS
        portals; an empty page is only accepted once there has been time for
        one to appear.
        """
        deadline = time.monotonic() + self._settings.browser_field_wait_timeout_seconds
        while True:
            entries = await self._discover()
            if entries or time.monotonic() >= deadline:
                return entries
            await asyncio.sleep(_FIELD_POLL_INTERVAL_SECONDS)

    async def _discover(
        self,
    ) -> list[tuple[int, int, Frame, dict[str, Any]]]:
        """Run the in-page discovery pass across the main document and
        every nested frame (ATS forms are routinely served inside one)."""
        found: list[tuple[int, int, Frame, dict[str, Any]]] = []
        for frame_index, frame in enumerate(self._page.frames):
            try:
                raw_fields = await frame.evaluate(FIELD_DISCOVERY_JS)
            except PlaywrightError as exc:
                # A frame detaching or navigating mid-read is ordinary on a
                # live page; the fields it held simply aren't in this
                # snapshot.
                logger.debug("Skipped frame %d during discovery: %s", frame_index, exc)
                continue
            if not isinstance(raw_fields, list):  # pragma: no cover - defensive
                continue
            for raw in raw_fields:
                if not isinstance(raw, dict):  # pragma: no cover - defensive
                    continue
                index = raw.get("index")
                if not isinstance(index, int):  # pragma: no cover - defensive
                    continue
                found.append((frame_index, index, frame, raw))
        return found

    async def _settle(self) -> None:
        """Give the page time to finish reacting to a press.

        Best-effort, exactly like the settle after navigation: a portal
        that holds a websocket open never goes network-idle, and that is
        not a reason to report a submission as failed when it went
        through.
        """
        try:
            await self._page.wait_for_load_state(
                "networkidle",
                timeout=self._settings.browser_settle_timeout_seconds * 1000,
            )
        except PlaywrightError as exc:
            logger.debug("Page did not go network-idle after the press: %s", exc)

    def _require_open(self) -> None:
        if self._closed:
            raise BrowserSessionClosedError(
                "This browser session is closed; open a new one to continue."
            )

    @staticmethod
    def _refuse_if_human_only(field: FormField) -> None:
        """Refuse any write to a field the domain marked as a boundary.

        The enforcement point for "ApplyFlow never solves CAPTCHAs, creates
        accounts, or enters passwords". It sits here — at the layer that
        actually types — rather than in a use case, because a rule enforced
        one level up is a rule the *next* caller has to remember. The
        judgment itself was made at discovery time by
        `HumanOnlyFieldPolicy`; this only obeys it.
        """
        boundary = field.human_only_boundary
        if boundary is None:
            return
        raise HumanOnlyFieldError(field.handle, boundary.value, field.label)

    def _entry(self, handle: str) -> _SnapshotEntry:
        self._require_open()
        entry = self._snapshot.get(handle)
        if entry is None:
            raise StaleFormFieldError(
                handle, "it is not part of this session's current form snapshot"
            )
        return entry

    async def _locate(self, entry: _SnapshotEntry) -> Locator:
        """Resolve a snapshot entry back to a live element, refusing to
        hand back one that is no longer the field it describes."""
        handle = entry.field.handle
        locator = entry.frame.locator(FIELD_SELECTOR).nth(entry.index)
        try:
            signature = await locator.evaluate(FIELD_SIGNATURE_JS)
        except PlaywrightTimeoutError as exc:
            raise StaleFormFieldError(
                handle, "no element is at its position on the page any more"
            ) from exc
        except PlaywrightError as exc:
            raise StaleFormFieldError(handle, _first_line(exc)) from exc
        if signature != entry.signature:
            raise StaleFormFieldError(
                handle, "the page changed and a different field is now in its place"
            )
        return locator

    async def _select(
        self, handle: str, locator: Locator, field: FormField, value: str
    ) -> None:
        option = match_option(field.options, value)
        if option is None:
            raise RejectedFieldValueError(
                handle, value, describe_options(field.options)
            )
        try:
            await locator.select_option(value=option.value)
        except PlaywrightError as exc:
            raise self._translate_write_failure(handle, value, field, exc) from exc

    async def _set_checked(
        self, handle: str, locator: Locator, field: FormField, value: str
    ) -> None:
        """Decide whether `value` ticks or unticks this control.

        Checkboxes and radios read the value in *opposite* order, and the
        difference is not cosmetic. A checkbox answers a yes/no question, so
        a boolean reading comes first: "no" on "I require visa sponsorship"
        must untick it.

        A radio is one option among several, so naming the option comes
        first — otherwise the "No" button in an ubiquitous Yes/No group
        would be unselectable, since `fill(no_button, "No")` would be read
        as "untick this" rather than as "choose No", which is plainly what
        the caller meant.
        """
        names_itself = matches_own_value(
            value=value, own_value=field.value, label=field.label
        )
        as_boolean = interpret_boolean(value)

        if field.kind is FormFieldKind.RADIO:
            if not names_itself and as_boolean is not True:
                # HTML offers no way to clear a radio, so a value that
                # doesn't select this one means "choose a different option"
                # — a handle the caller already holds.
                raise RejectedFieldValueError(
                    handle,
                    value,
                    "a value that selects it (its own label, or 'yes'/'true') — "
                    "a radio cannot be cleared, so fill the option you want instead",
                )
            desired = True
        else:
            if as_boolean is None:
                if not names_itself:
                    raise RejectedFieldValueError(handle, value, _BOOLEAN_HELP)
                desired = True
            else:
                desired = as_boolean

        try:
            await locator.set_checked(desired)
        except PlaywrightError as exc:
            raise self._translate_write_failure(handle, value, field, exc) from exc

    def _translate_write_failure(
        self, handle: str, value: str, field: FormField, exc: PlaywrightError
    ) -> BrowserAutomationError:
        """Sort a failed write into "the value was wrong" vs. "the element
        would not take input".

        The split is driven by Playwright's own message, which is the only
        place the distinction exists: a date input handed `"tomorrow"`
        reports a malformed value, while an element behind a cookie banner
        reports a timeout. Recognizing the former by message text is a
        knowing trade — worth it because a caller can act on "pick a
        different value" and cannot act on "something went wrong".
        """
        message = _first_line(exc)
        if "malformed value" in message.casefold():
            accepted = (
                describe_options(field.options)
                if field.options
                else f"a value the '{field.kind}' input type accepts"
            )
            return RejectedFieldValueError(handle, value, accepted)
        if isinstance(exc, PlaywrightTimeoutError):
            return FormFieldNotFillableError(
                handle,
                "it did not become editable in time (it may be obscured, "
                f"or the page may have moved on): {message}",
            )
        return FormFieldNotFillableError(handle, message)


class PlaywrightBrowserAutomation(BrowserAutomationPort):
    """A lazily launched Chromium that hands out isolated form sessions."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._sessions: set[PlaywrightBrowserSession] = set()
        #: Serializes launch and shutdown so concurrent `open()` calls
        #: share one browser instead of racing to launch several.
        self._lifecycle_lock = asyncio.Lock()

    async def open(self, url: str) -> BrowserSessionPort:
        browser = await self._browser_instance()
        context = await browser.new_context(**self._context_options())
        context.set_default_timeout(
            self._settings.browser_action_timeout_seconds * 1000
        )
        context.set_default_navigation_timeout(
            self._settings.browser_navigation_timeout_seconds * 1000
        )
        try:
            page = await context.new_page()
            await self._navigate(page, url)
            await self._settle(page)
        except BaseException:
            # A caller that never received a session must not be left
            # holding a context to clean up.
            await _close_quietly(context)
            raise

        session = PlaywrightBrowserSession(
            page=page,
            context=context,
            settings=self._settings,
            on_closed=self._sessions.discard,
        )
        self._sessions.add(session)
        return session

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            for session in tuple(self._sessions):
                try:
                    await session.close()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Failed to close a browser session: %s", exc)
            self._sessions.clear()

            browser, self._browser = self._browser, None
            playwright, self._playwright = self._playwright, None
            if browser is not None:
                try:
                    await browser.close()
                except PlaywrightError as exc:
                    logger.debug("Browser was already gone on shutdown: %s", exc)
            if playwright is not None:
                await playwright.stop()

    # -- internals ---------------------------------------------------------

    async def _browser_instance(self) -> Browser:
        async with self._lifecycle_lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            # A browser that died (crash, OOM kill) is replaced rather than
            # reused; its contexts are already gone either way.
            if self._browser is not None:
                self._sessions.clear()
                self._browser = None
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=self._settings.browser_headless,
                    args=list(self._settings.browser_launch_args),
                )
            except PlaywrightError as exc:
                raise BrowserAutomationError(
                    "Could not launch Chromium for portal automation. The browser "
                    "build Playwright expects may not be installed on this host — "
                    f"try `playwright install chromium`. Underlying error: "
                    f"{_first_line(exc)}"
                ) from exc
            return self._browser

    def _context_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "viewport": {
                "width": self._settings.browser_viewport_width,
                "height": self._settings.browser_viewport_height,
            }
        }
        if self._settings.browser_user_agent:
            options["user_agent"] = self._settings.browser_user_agent
        return options

    async def _navigate(self, page: Page, url: str) -> None:
        max_attempts = self._settings.browser_navigation_max_retries + 1
        reason = "the navigation never completed"

        for attempt in range(1, max_attempts + 1):
            try:
                response = await page.goto(url, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                reason = (
                    "it did not load within "
                    f"{self._settings.browser_navigation_timeout_seconds:.0f}s"
                )
            except PlaywrightError as exc:
                reason = _first_line(exc)
            else:
                # `None` means a same-document navigation (a fragment
                # change) with no HTTP exchange to judge — the document is
                # loaded, which is all this call promises.
                if response is None or response.status < 400:
                    return
                reason = f"the portal responded {response.status}"
                if response.status not in _RETRYABLE_STATUS_CODES:
                    raise BrowserNavigationError(url, reason)

            if attempt == max_attempts:
                break
            delay = _backoff_delay(
                attempt,
                self._settings.browser_navigation_retry_base_delay_seconds,
                self._settings.browser_navigation_retry_max_delay_seconds,
            )
            logger.warning(
                "Navigation to an apply URL failed (%s) on attempt %d/%d, "
                "retrying in %.1fs",
                reason,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

        raise BrowserNavigationError(url, f"{reason} after {max_attempts} attempt(s)")

    async def _settle(self, page: Page) -> None:
        """Give a JS-rendered form a chance to paint its fields.

        Best-effort by design: `networkidle` never arriving is normal on a
        page that polls or holds a websocket open, and is not a reason to
        fail a navigation that already loaded.
        """
        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=self._settings.browser_settle_timeout_seconds * 1000,
            )
        except PlaywrightError as exc:
            logger.debug("Page did not go network-idle after load: %s", exc)


async def _close_quietly(context: BrowserContext) -> None:
    try:
        await context.close()
    except PlaywrightError as exc:  # pragma: no cover - defensive
        logger.debug("Failed to close a browser context: %s", exc)


def _first_line(exc: PlaywrightError) -> str:
    """Playwright errors carry a multi-line call log; only the first line
    says what went wrong."""
    message = getattr(exc, "message", None) or str(exc)
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    return lines[0] if lines else "unknown browser error"


def _backoff_delay(
    attempt: int, retry_base_delay: float, retry_max_delay: float
) -> float:
    return float(min(retry_base_delay * (2 ** (attempt - 1)), retry_max_delay))
