"""Tests for PlaywrightBrowserAutomation — the browser harness every
autofill capability builds on.

These drive a **real headless Chromium** against a **real local HTTP
server**. No mocks: the whole value of this layer is that it behaves
correctly against actual HTML, actual page lifecycle timing, and actual
navigation failures, none of which a fake page object would reproduce. The
server is bound to 127.0.0.1 on an ephemeral port and serves only the
fixtures below, so nothing here touches the network.

The module skips itself when Chromium isn't installed (`playwright install
chromium`) rather than failing the suite, matching how the repo treats its
other environment-dependent checks.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from http import HTTPStatus

import pytest
import pytest_asyncio

from src.application.exceptions import (
    BrowserNavigationError,
    BrowserSessionClosedError,
    FormFieldNotFillableError,
    HumanOnlyFieldError,
    RejectedFieldValueError,
    StaleFormFieldError,
)
from src.application.ports.browser_automation_port import FormField, FormFieldKind
from src.domain.services.hard_stop_detector import HardStopDetector
from src.domain.value_objects.hard_stop_kind import HardStopKind
from src.infrastructure.browser_automation.playwright_browser_automation import (
    PlaywrightBrowserAutomation,
)
from src.infrastructure.config import Settings

# --- page fixtures ---------------------------------------------------------

APPLICATION_FORM_HTML = """<!doctype html>
<html><body>
<h1>Apply: Senior Backend Engineer</h1>
<form>
  <label for="full-name">Full name *</label>
  <input id="full-name" name="full_name" type="text" required maxlength="80"
         placeholder="Ada Lovelace" autocomplete="name">

  <label for="email">Email</label>
  <input id="email" name="email" type="email" required>

  <label for="phone">Phone</label>
  <input id="phone" name="phone" type="tel">

  <label for="site">Website</label>
  <input id="site" name="website" type="url">

  <label for="years">Years of experience</label>
  <input id="years" name="years" type="number">

  <label for="start">Earliest start date</label>
  <input id="start" name="start_date" type="date">

  <label for="cover">Why do you want to work here?</label>
  <textarea id="cover" name="cover_letter" maxlength="4000"></textarea>

  <label for="country">Country</label>
  <select id="country" name="country">
    <option value="">Select a country</option>
    <option value="us">United States</option>
    <option value="ca">Canada</option>
  </select>

  <label for="resume">Resume</label>
  <input id="resume" name="resume" type="file">

  <label><input type="checkbox" name="sponsorship" value="yes">
    I require visa sponsorship</label>

  <fieldset>
    <legend>Authorized to work in the US?</legend>
    <label><input type="radio" name="authorized" value="yes"> Yes</label>
    <label><input type="radio" name="authorized" value="no"> No</label>
  </fieldset>

  <input type="hidden" name="csrf" value="a-secret">
  <input type="text" name="referral" value="locked" readonly>
  <input type="text" name="legacy_field" disabled>
  <input type="text" name="offscreen" style="display: none">
  <input type="submit" value="Submit application">
  <button type="button">Cancel</button>
</form>
</body></html>
"""

NO_FORM_HTML = """<!doctype html>
<html><body><h1>This posting is no longer accepting applications.</h1></body></html>
"""

EMBEDDED_FORM_HTML = """<!doctype html>
<html><body>
<input name="outer" aria-label="Outer question">
<iframe width="400" height="200" srcdoc="
  <label for='inner'>Inner question</label><input id='inner' name='inner'>
"></iframe>
</body></html>
"""

#: Typing into the first field inserts a new field ahead of it, shifting
#: every position after it. Exactly the drift a snapshot handle must not
#: silently follow.
SHIFTING_FORM_HTML = """<!doctype html>
<html><body>
<form id="f">
  <input name="trigger" aria-label="Trigger" oninput="insertField()">
  <input name="target" aria-label="Target">
</form>
<script>
  function insertField() {
    const form = document.getElementById('f');
    const inserted = document.createElement('input');
    inserted.setAttribute('name', 'inserted');
    inserted.setAttribute('aria-label', 'Inserted');
    form.insertBefore(inserted, form.firstChild);
  }
</script>
</body></html>
"""

#: Reports the cookies visible on load, then sets one. A second session in
#: the same browser context would report the cookie the first one left.
COOKIE_HTML = """<!doctype html>
<html><body>
<input id="c" aria-label="Cookies seen on load">
<script>
  document.getElementById('c').value = document.cookie;
  document.cookie = 'applyflow_seen=1';
</script>
</body></html>
"""


# --- local HTTP server -----------------------------------------------------

_Route = Callable[[], Awaitable[tuple[int, str]]]


class _FormServer:
    """A minimal HTTP/1.1 server over asyncio, serving the fixtures above.

    Hand-rolled rather than `http.server` so a route can return an
    arbitrary status, fail a set number of times before succeeding, or hang
    until released — the three navigation-failure shapes under test.
    """

    def __init__(self) -> None:
        self._routes: dict[str, _Route] = {}
        self.requests: dict[str, int] = {}
        self._release = asyncio.Event()
        self._server: asyncio.AbstractServer | None = None
        self.port = 0

    def page(self, path: str, html: str, status: int = 200) -> str:
        async def route() -> tuple[int, str]:
            return status, html

        self._routes[path] = route
        return self.url(path)

    def failing_then_serving(
        self, path: str, html: str, *, failures: int, status: int = 503
    ) -> str:
        """A route that answers `status` for its first `failures` requests
        and then serves the page — a portal briefly under load."""
        remaining = [failures]

        async def route() -> tuple[int, str]:
            if remaining[0] > 0:
                remaining[0] -= 1
                return status, "<h1>Temporarily unavailable</h1>"
            return 200, html

        self._routes[path] = route
        return self.url(path)

    def hanging(self, path: str) -> str:
        """A route that accepts the connection and never answers until the
        server is torn down — what a timeout actually looks like."""

        async def route() -> tuple[int, str]:
            await self._release.wait()
            return 200, "<h1>Finally</h1>"

        self._routes[path] = route
        return self.url(path)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        # Released first so a hanging handler finishes instead of holding
        # `wait_closed` open for the length of its own timeout.
        self._release.set()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return
            parts = request_line.decode("latin-1").split()
            path = parts[1].split("?")[0] if len(parts) > 1 else "/"
            while True:  # drain headers
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break

            self.requests[path] = self.requests.get(path, 0) + 1
            route = self._routes.get(path)
            if route is None:
                status, body = 404, "<h1>Not found</h1>"
            else:
                status, body = await route()

            payload = body.encode("utf-8")
            phrase = HTTPStatus(status).phrase
            head = (
                f"HTTP/1.1 {status} {phrase}\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(payload)}\r\n"
                "Connection: close\r\n\r\n"
            )
            writer.write(head.encode("latin-1") + payload)
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass  # the browser gave up on this request; nothing to report
        finally:
            writer.close()


# --- fixtures --------------------------------------------------------------


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "browser_headless": True,
        # Tight but generous enough to be stable on a loaded CI box.
        "browser_navigation_timeout_seconds": 10.0,
        "browser_action_timeout_seconds": 3.0,
        "browser_settle_timeout_seconds": 2.0,
        "browser_field_wait_timeout_seconds": 1.0,
        # Retries are opted into per test: a suite that silently retried
        # every failure would hide which failures are retried at all.
        "browser_navigation_max_retries": 0,
        "browser_navigation_retry_base_delay_seconds": 0.01,
        "browser_navigation_retry_max_delay_seconds": 0.02,
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest_asyncio.fixture
async def server() -> AsyncIterator[_FormServer]:
    form_server = _FormServer()
    await form_server.start()
    try:
        yield form_server
    finally:
        await form_server.stop()


async def _harness_with(**overrides: object) -> PlaywrightBrowserAutomation:
    """A harness whose browser is already launched.

    Launching eagerly here is what lets a host without the Chromium build
    Playwright expects *skip* these tests instead of failing them — the same
    treatment the repo gives its other environment-dependent checks. Callers
    own the returned harness and must shut it down.
    """
    automation = PlaywrightBrowserAutomation(_settings(**overrides))
    try:
        await automation._browser_instance()
    except Exception as exc:  # noqa: BLE001 - any launch failure means skip
        await automation.shutdown()
        pytest.skip(f"Chromium is not available: {exc}")
    return automation


@pytest_asyncio.fixture
async def harness() -> AsyncIterator[PlaywrightBrowserAutomation]:
    """A harness on a real Chromium, always shut down afterwards."""
    automation = await _harness_with()
    try:
        yield automation
    finally:
        await automation.shutdown()


def _by_name(fields: tuple[FormField, ...], name: str) -> FormField:
    matches = [field for field in fields if field.name == name]
    assert matches, f"no field named '{name}' in {[f.name for f in fields]}"
    return matches[0]


# --- navigation ------------------------------------------------------------


async def test_open_loads_the_form_and_reports_the_landed_url(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        assert session.current_url == url


async def test_a_404_is_a_navigation_error_and_is_not_retried(harness, server):
    url = server.page("/gone", "<h1>Gone</h1>", status=404)

    with pytest.raises(BrowserNavigationError) as caught:
        await harness.open(url)

    assert "404" in str(caught.value)
    assert caught.value.url == url
    # The portal answered definitively; retrying it only wastes the budget.
    assert server.requests["/gone"] == 1


async def test_a_503_is_retried_and_the_session_opens_on_the_retry(server):
    harness = await _harness_with(browser_navigation_max_retries=1)
    url = server.failing_then_serving("/apply", APPLICATION_FORM_HTML, failures=1)
    try:
        session = await harness.open(url)
        fields = await session.read_fields()
        assert _by_name(fields, "email").kind is FormFieldKind.EMAIL
        assert server.requests["/apply"] == 2
    finally:
        await harness.shutdown()


async def test_navigation_gives_up_once_the_retry_budget_is_spent(server):
    harness = await _harness_with(browser_navigation_max_retries=2)
    url = server.failing_then_serving("/apply", APPLICATION_FORM_HTML, failures=99)
    try:
        with pytest.raises(BrowserNavigationError) as caught:
            await harness.open(url)
        assert "3 attempt(s)" in str(caught.value)
        assert server.requests["/apply"] == 3
    finally:
        await harness.shutdown()


async def test_a_page_that_never_responds_is_a_navigation_error(server):
    harness = await _harness_with(browser_navigation_timeout_seconds=1.0)
    url = server.hanging("/slow")
    try:
        with pytest.raises(BrowserNavigationError) as caught:
            await harness.open(url)
        assert "did not load" in str(caught.value)
    finally:
        await harness.shutdown()


async def test_an_unreachable_host_is_a_navigation_error(harness):
    # Port 0 is never listening, so this fails at connect time rather than
    # anywhere near a timeout.
    with pytest.raises(BrowserNavigationError):
        await harness.open("http://127.0.0.1:1/apply")


async def test_a_failed_open_leaves_no_browser_context_behind(harness, server):
    """A caller that never received a session has nothing to clean up, so
    the harness must not be holding a context on its behalf."""
    url = server.page("/gone", "<h1>Gone</h1>", status=404)

    with pytest.raises(BrowserNavigationError):
        await harness.open(url)

    assert harness._browser is not None
    assert harness._browser.contexts == []


# --- reading fields --------------------------------------------------------


async def test_read_fields_describes_every_fillable_field_in_order(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

    assert [field.kind for field in fields] == [
        FormFieldKind.TEXT,
        FormFieldKind.EMAIL,
        FormFieldKind.PHONE,
        FormFieldKind.URL,
        FormFieldKind.NUMBER,
        FormFieldKind.DATE,
        FormFieldKind.TEXTAREA,
        FormFieldKind.SELECT,
        FormFieldKind.FILE,
        FormFieldKind.CHECKBOX,
        FormFieldKind.RADIO,
        FormFieldKind.RADIO,
    ]


async def test_read_fields_excludes_everything_a_caller_must_not_touch(harness, server):
    """Hidden, disabled, read-only, invisible, and submit controls are all
    absent — which is also why nothing this harness returns can submit."""
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

    names = {field.name for field in fields}
    assert names.isdisjoint(
        {"csrf", "referral", "legacy_field", "offscreen", "", "Submit application"}
    )
    assert not any(field.value == "a-secret" for field in fields)


async def test_read_fields_resolves_labels_from_the_markup(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

    assert _by_name(fields, "full_name").label == "Full name *"
    # A wrapping <label> with no `for` still names its control.
    assert _by_name(fields, "sponsorship").label == "I require visa sponsorship"
    assert [f.label for f in fields if f.name == "authorized"] == ["Yes", "No"]


async def test_read_fields_carries_the_metadata_autofill_needs(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

    full_name = _by_name(fields, "full_name")
    assert full_name.required is True
    assert full_name.placeholder == "Ada Lovelace"
    assert full_name.max_length == 80
    assert full_name.attributes["autocomplete"] == "name"
    assert full_name.attributes["id"] == "full-name"

    assert _by_name(fields, "cover_letter").max_length == 4000
    assert _by_name(fields, "phone").required is False
    assert _by_name(fields, "phone").max_length is None


async def test_read_fields_reports_a_selects_options_in_page_order(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

    country = _by_name(fields, "country")
    assert [(option.label, option.value) for option in country.options] == [
        ("Select a country", ""),
        ("United States", "us"),
        ("Canada", "ca"),
    ]
    assert _by_name(fields, "phone").options == ()


async def test_read_fields_finds_fields_inside_an_embedded_frame(harness, server):
    """ATS forms are routinely served inside an iframe; a harness that only
    read the main document would find nothing to fill on them."""
    url = server.page("/embedded", EMBEDDED_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

        labels = {field.label for field in fields}
        assert labels == {"Outer question", "Inner question"}

        inner = _by_name(fields, "inner")
        await session.fill(inner.handle, "answered inside the frame")
        assert _by_name(await session.read_fields(), "inner").value == (
            "answered inside the frame"
        )


async def test_a_page_with_no_form_reads_as_empty_rather_than_failing(harness, server):
    """A dead posting or a login wall is data, not an error — the caller
    decides what to do about a form that isn't there."""
    url = server.page("/closed", NO_FORM_HTML)
    async with await harness.open(url) as session:
        assert await session.read_fields() == ()


# --- filling fields --------------------------------------------------------


async def test_fill_writes_text_and_the_page_reflects_it(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()
        await session.fill(_by_name(fields, "full_name").handle, "Ada Lovelace")
        await session.fill(_by_name(fields, "email").handle, "ada@example.com")
        await session.fill(
            _by_name(fields, "cover_letter").handle, "I build reliable systems."
        )

        refreshed = await session.read_fields()
        assert _by_name(refreshed, "full_name").value == "Ada Lovelace"
        assert _by_name(refreshed, "email").value == "ada@example.com"
        assert _by_name(refreshed, "cover_letter").value == "I build reliable systems."


async def test_fill_selects_an_option_by_its_label(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()
        await session.fill(_by_name(fields, "country").handle, "Canada")

        country = _by_name(await session.read_fields(), "country")
        assert country.value == "ca"


async def test_fill_selects_an_option_by_its_submitted_value(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()
        await session.fill(_by_name(fields, "country").handle, "us")

        assert _by_name(await session.read_fields(), "country").value == "us"


async def test_a_value_that_names_no_option_is_rejected_with_the_options(
    harness, server
):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()
        country = _by_name(fields, "country")

        with pytest.raises(RejectedFieldValueError) as caught:
            await session.fill(country.handle, "Atlantis")

        assert "United States" in str(caught.value)
        # Nothing was chosen — a rejected value must not half-apply.
        assert _by_name(await session.read_fields(), "country").value == ""


async def test_fill_ticks_and_unticks_a_checkbox(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()
        sponsorship = _by_name(fields, "sponsorship")
        assert sponsorship.checked is False

        await session.fill(sponsorship.handle, "yes")
        assert _by_name(await session.read_fields(), "sponsorship").checked is True

        await session.fill(
            _by_name(await session.read_fields(), "sponsorship").handle, "no"
        )
        assert _by_name(await session.read_fields(), "sponsorship").checked is False


async def test_fill_selects_a_radio_by_its_label(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()
        yes = [f for f in fields if f.name == "authorized"][0]

        await session.fill(yes.handle, "Yes")

        authorized = [f for f in await session.read_fields() if f.name == "authorized"]
        assert [field.checked for field in authorized] == [True, False]


async def test_the_no_option_of_a_yes_no_radio_group_is_selectable(harness, server):
    """Naming the option wins over reading the value as a boolean on a
    radio. Otherwise the "No" button of an ubiquitous Yes/No group would be
    unselectable, since "No" would be read as "clear this" instead of the
    "choose No" the caller plainly meant."""
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()
        no = [f for f in fields if f.name == "authorized"][1]

        await session.fill(no.handle, "No")

        authorized = [f for f in await session.read_fields() if f.name == "authorized"]
        assert [field.checked for field in authorized] == [False, True]


async def test_a_radio_cannot_be_cleared(harness, server):
    """HTML offers no way to clear a radio, so "no" aimed at the *Yes*
    button means "choose the other option" — a handle the caller already
    holds, not something to guess at here."""
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()
        yes = [f for f in fields if f.name == "authorized"][0]

        with pytest.raises(RejectedFieldValueError) as caught:
            await session.fill(yes.handle, "no")

        assert "cannot be cleared" in str(caught.value)
        authorized = [f for f in await session.read_fields() if f.name == "authorized"]
        assert [field.checked for field in authorized] == [False, False]


async def test_a_checkbox_rejects_a_value_that_is_neither_boolean_nor_its_own(
    harness, server
):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

        with pytest.raises(RejectedFieldValueError) as caught:
            await session.fill(_by_name(fields, "sponsorship").handle, "perhaps")

        assert "yes" in str(caught.value)


async def test_text_cannot_be_written_into_a_file_input(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

        with pytest.raises(FormFieldNotFillableError) as caught:
            await session.fill(_by_name(fields, "resume").handle, "/etc/passwd")

        assert "attach_file" in str(caught.value)


async def test_a_file_cannot_be_attached_to_a_text_field(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

        with pytest.raises(FormFieldNotFillableError):
            await session.attach_file(
                _by_name(fields, "full_name").handle,
                filename="resume.pdf",
                content=b"%PDF-1.4",
            )


async def test_a_malformed_date_is_reported_as_a_rejected_value(harness, server):
    """Distinguishing "pick a different value" from "the field wouldn't
    take input" is the difference between a caller that can recover and one
    that can only give up."""
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

        with pytest.raises(RejectedFieldValueError):
            await session.fill(_by_name(fields, "start_date").handle, "next Tuesday")


# --- attaching files -------------------------------------------------------


async def test_attach_file_uploads_bytes_under_a_bare_filename(harness, server):
    """The filename crosses into a multipart upload, so a path is reduced to
    its last segment before the portal ever sees it."""
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

        await session.attach_file(
            _by_name(fields, "resume").handle,
            filename="../../etc/ada-lovelace-resume.pdf",
            content=b"%PDF-1.4 tailored resume",
        )

        resume = _by_name(await session.read_fields(), "resume")
        # Chromium reports a file input's value as C:\fakepath\<name>.
        assert resume.value.endswith("ada-lovelace-resume.pdf")
        assert "etc" not in resume.value


async def test_attach_file_rejects_a_filename_that_is_only_a_path(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()

        with pytest.raises(RejectedFieldValueError):
            await session.attach_file(
                _by_name(fields, "resume").handle, filename="../../", content=b"x"
            )


# --- handle integrity ------------------------------------------------------


async def test_an_unknown_handle_is_rejected(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        await session.read_fields()

        with pytest.raises(StaleFormFieldError):
            await session.fill("g1-f0-999999", "anything")


async def test_handles_from_an_earlier_snapshot_are_rejected(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        stale = _by_name(await session.read_fields(), "full_name")
        await session.read_fields()

        with pytest.raises(StaleFormFieldError) as caught:
            await session.fill(stale.handle, "Ada Lovelace")

        assert "read_fields()" in str(caught.value)


async def test_a_handle_is_rejected_when_the_page_shifts_underneath_it(harness, server):
    """The failure this harness exists to prevent: typing into one field
    inserts another ahead of it, so every later position now points at a
    different question. Writing there anyway would put an answer in the
    wrong box, silently, on a real application."""
    url = server.page("/shifting", SHIFTING_FORM_HTML)
    async with await harness.open(url) as session:
        fields = await session.read_fields()
        trigger = _by_name(fields, "trigger")
        target = _by_name(fields, "target")

        await session.fill(trigger.handle, "typing here inserts a field")

        with pytest.raises(StaleFormFieldError) as caught:
            await session.fill(target.handle, "must not land in the wrong field")

        assert "different field" in str(caught.value)

        # Re-reading is the remedy, and it works.
        refreshed = await session.read_fields()
        await session.fill(_by_name(refreshed, "target").handle, "now in the right box")
        assert _by_name(await session.read_fields(), "target").value == (
            "now in the right box"
        )


# --- screenshots -----------------------------------------------------------


async def test_screenshot_returns_png_bytes(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        image = await session.screenshot()

    assert image.startswith(b"\x89PNG\r\n\x1a\n")


# --- lifecycle and cleanup -------------------------------------------------


async def test_close_is_idempotent_and_a_closed_session_refuses_everything(
    harness, server
):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    session = await harness.open(url)
    fields = await session.read_fields()
    handle = fields[0].handle

    await session.close()
    await session.close()  # idempotent

    with pytest.raises(BrowserSessionClosedError):
        await session.read_fields()
    with pytest.raises(BrowserSessionClosedError):
        await session.fill(handle, "too late")
    with pytest.raises(BrowserSessionClosedError):
        await session.screenshot()
    with pytest.raises(BrowserSessionClosedError):
        _ = session.current_url


async def test_closing_a_session_releases_its_browser_context(harness, server):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    session = await harness.open(url)
    assert len(harness._browser.contexts) == 1

    await session.close()

    assert harness._browser.contexts == []


async def test_sessions_are_isolated_from_each_others_cookies(harness, server):
    """Each session gets its own browser context, so one application's
    portal cookies cannot follow the candidate into the next."""
    url = server.page("/cookies", COOKIE_HTML)

    async with await harness.open(url) as first:
        first_seen = (await first.read_fields())[0].value
    async with await harness.open(url) as second:
        second_seen = (await second.read_fields())[0].value

    assert first_seen == ""
    # A shared context would surface the cookie the first session set.
    assert second_seen == ""


async def test_two_sessions_can_be_open_on_different_pages_at_once(harness, server):
    apply_url = server.page("/apply", APPLICATION_FORM_HTML)
    embedded_url = server.page("/embedded", EMBEDDED_FORM_HTML)

    async with (
        await harness.open(apply_url) as first,
        await harness.open(embedded_url) as second,
    ):
        assert first.current_url == apply_url
        assert second.current_url == embedded_url
        assert len(harness._browser.contexts) == 2

        first_fields = await first.read_fields()
        second_fields = await second.read_fields()

        await first.fill(_by_name(first_fields, "full_name").handle, "Ada")
        await second.fill(_by_name(second_fields, "outer").handle, "Grace")

        assert _by_name(await first.read_fields(), "full_name").value == "Ada"
        assert _by_name(await second.read_fields(), "outer").value == "Grace"


async def test_shutdown_closes_open_sessions_and_the_browser(server):
    # Not the `harness` fixture: this test shuts the harness down itself,
    # which is the behavior under test.
    harness = await _harness_with()
    url = server.page("/apply", APPLICATION_FORM_HTML)

    first = await harness.open(url)
    second = await harness.open(url)
    browser = harness._browser

    await harness.shutdown()

    # The backstop: sessions nobody closed are closed, and no browser
    # process is left behind.
    for session in (first, second):
        with pytest.raises(BrowserSessionClosedError):
            await session.read_fields()
    assert browser.is_connected() is False

    await harness.shutdown()  # idempotent

    # And the harness is reusable — a later open() launches a fresh browser.
    async with await harness.open(url) as reopened:
        assert reopened.current_url == url
    await harness.shutdown()


# --- hard boundaries: page signals -----------------------------------------
#
# These drive the real detection path end to end: a real page, the real
# in-page signal pass, and the real domain detector. Unit tests cover the
# rules from literals (tests/domain/test_hard_stop_detector.py); what can
# only be checked here is that the collection pass actually hands the domain
# the facts those rules need — from a real DOM, including inside frames.


CAPTCHA_FORM_HTML = """<!doctype html>
<html><head><title>Apply — Globex</title>
<script src="/vendor/recaptcha/api.js"></script></head>
<body>
<h1>Apply: Senior Backend Engineer</h1>
<form>
  <label for="name">Full name</label>
  <input id="name" name="full_name">
  <div class="g-recaptcha" data-sitekey="6LcExampleSiteKey"></div>
</form>
</body></html>
"""

LOGIN_WALL_HTML = """<!doctype html>
<html><head><title>Sign in — Globex Careers</title></head>
<body>
<h1>Sign in to continue</h1>
<form>
  <label for="email">Email</label>
  <input id="email" name="email" type="email">
  <label for="pw">Password</label>
  <input id="pw" name="password" type="password" autocomplete="current-password">
</form>
<p>Already have an account? Forgot your password?</p>
</body></html>
"""

SIGNATURE_FORM_HTML = """<!doctype html>
<html><head><title>Authorization — Globex</title></head>
<body>
<form>
  <label for="name">Full name</label>
  <input id="name" name="full_name">
  <p>Type your full name to sign this authorization electronically.</p>
  <label for="sig">Applicant signature</label>
  <input id="sig" name="applicant_signature">
  <canvas class="signature-pad" width="300" height="100"></canvas>
</form>
</body></html>
"""

#: A challenge answer box and a masked credential that lies about its type —
#: the two shapes a field-level refusal has to catch that a `type` check alone
#: would not.
DISGUISED_FIELDS_HTML = """<!doctype html>
<html><body>
<form>
  <label for="a">Full name</label>
  <input id="a" name="full_name">
  <label for="b">Enter the characters you see</label>
  <input id="b" name="g-recaptcha-response">
  <label for="c">Account access</label>
  <input id="c" name="user_password" type="text" autocomplete="current-password">
  <label for="d">Signed offer letter</label>
  <input id="d" name="signature_upload" type="file">
</form>
</body></html>
"""

#: An ordinary outer page whose embedded frame is the login wall. A reading
#: that stopped at the main document would call this page clean.
EMBEDDED_LOGIN_HTML = """<!doctype html>
<html><head><title>Careers — Globex</title></head><body>
<h1>Senior Backend Engineer</h1>
<iframe width="400" height="300" srcdoc="
  <h2>Sign in to continue</h2>
  <label for='pw'>Password</label><input id='pw' type='password'>
"></iframe>
</body></html>
"""


async def test_page_signals_describe_an_ordinary_form_without_flagging_it(
    harness, server
):
    url = server.page("/apply", APPLICATION_FORM_HTML)
    async with await harness.open(url) as session:
        signals = await session.read_page_signals()
        fields = await session.read_fields()

    assert signals.url == url
    assert "Senior Backend Engineer" in signals.text
    assert signals.password_field_count == 0
    # The detector's view of the form is exactly the form the harness would
    # fill — both come from the one discovery pass.
    assert signals.fillable_field_count == len(fields)
    assert "Full name *" in signals.field_labels
    assert HardStopDetector().detect(signals) == ()


async def test_a_captcha_widget_on_a_real_page_is_detected(harness, server):
    url = server.page("/apply", CAPTCHA_FORM_HTML)
    async with await harness.open(url) as session:
        signals = await session.read_page_signals()

    stops = HardStopDetector().detect(signals)

    assert [stop.kind for stop in stops] == [HardStopKind.CAPTCHA]
    # Recognized from the markup and the script it pulls in — the widget
    # itself never rendered, since nothing here talks to the network.
    assert any("recaptcha" in hint for hint in signals.element_hints)
    assert any("recaptcha" in script for script in signals.script_urls)


async def test_a_login_wall_on_a_real_page_is_detected(harness, server):
    url = server.page("/login", LOGIN_WALL_HTML)
    async with await harness.open(url) as session:
        signals = await session.read_page_signals()

    stops = HardStopDetector().detect(signals)

    assert [stop.kind for stop in stops] == [HardStopKind.ACCOUNT_WALL]
    assert signals.password_field_count == 1
    assert stops[0].evidence[0] == "the form presents 1 password field"


async def test_a_signature_block_on_a_real_page_is_detected(harness, server):
    url = server.page("/sign", SIGNATURE_FORM_HTML)
    async with await harness.open(url) as session:
        signals = await session.read_page_signals()

    stops = HardStopDetector().detect(signals)

    assert [stop.kind for stop in stops] == [HardStopKind.ELECTRONIC_SIGNATURE]
    assert "Applicant signature" in signals.field_labels


async def test_signals_are_read_from_inside_frames_too(harness, server):
    """ATS forms are routinely embedded, so a wall inside the frame is still
    a wall — and a reading that stopped at the outer document would miss it."""
    url = server.page("/embedded-login", EMBEDDED_LOGIN_HTML)
    async with await harness.open(url) as session:
        signals = await session.read_page_signals()

    assert signals.password_field_count == 1
    assert "sign in to continue" in signals.readable_text
    assert [stop.kind for stop in HardStopDetector().detect(signals)] == [
        HardStopKind.ACCOUNT_WALL
    ]


async def test_a_page_with_no_form_still_yields_signals(harness, server):
    """A dead posting or an interstitial presents nothing fillable, and its
    URL and text are frequently the whole story."""
    url = server.page("/gone-but-200", NO_FORM_HTML)
    async with await harness.open(url) as session:
        signals = await session.read_page_signals()

    assert signals.url == url
    assert signals.fillable_field_count == 0
    assert "no longer accepting applications" in signals.text


# --- hard boundaries: refusing to write ------------------------------------


async def test_a_password_field_is_reported_but_can_never_be_filled(harness, server):
    """Reported, because it is the evidence a hand-off is needed. Unfillable,
    because ApplyFlow never types a credential."""
    url = server.page("/login", LOGIN_WALL_HTML)
    async with await harness.open(url) as session:
        password = _by_name(await session.read_fields(), "password")

        assert password.kind is FormFieldKind.PASSWORD
        assert password.human_only_boundary is HardStopKind.ACCOUNT_WALL
        assert password.is_human_only is True

        with pytest.raises(HumanOnlyFieldError) as caught:
            await session.fill(password.handle, "hunter2")

        # Nothing was typed: the refusal happens before the element is even
        # located, and the page proves it.
        assert _by_name(await session.read_fields(), "password").value == ""

    assert caught.value.boundary == HardStopKind.ACCOUNT_WALL.value
    assert "never solves CAPTCHAs" in str(caught.value)
    # The attempted value is never echoed — that would put a credential in a
    # log line.
    assert "hunter2" not in str(caught.value)


async def test_a_challenge_answer_box_cannot_be_filled(harness, server):
    url = server.page("/disguised", DISGUISED_FIELDS_HTML)
    async with await harness.open(url) as session:
        captcha_field = _by_name(await session.read_fields(), "g-recaptcha-response")

        assert captcha_field.human_only_boundary is HardStopKind.CAPTCHA

        with pytest.raises(HumanOnlyFieldError) as caught:
            await session.fill(captcha_field.handle, "ABC123")

    assert caught.value.boundary == HardStopKind.CAPTCHA.value


async def test_a_credential_masked_as_a_text_input_cannot_be_filled(harness, server):
    """`type="text"` with a password name and autocomplete hint. A refusal
    driven only by the input type would have typed into this one."""
    url = server.page("/disguised", DISGUISED_FIELDS_HTML)
    async with await harness.open(url) as session:
        disguised = _by_name(await session.read_fields(), "user_password")

        assert disguised.kind is FormFieldKind.TEXT
        assert disguised.human_only_boundary is HardStopKind.ACCOUNT_WALL

        with pytest.raises(HumanOnlyFieldError):
            await session.fill(disguised.handle, "hunter2")


async def test_a_signature_field_cannot_be_filled(harness, server):
    url = server.page("/sign", SIGNATURE_FORM_HTML)
    async with await harness.open(url) as session:
        signature = _by_name(await session.read_fields(), "applicant_signature")

        with pytest.raises(HumanOnlyFieldError) as caught:
            await session.fill(signature.handle, "Ada Lovelace")

        assert _by_name(await session.read_fields(), "applicant_signature").value == ""

    assert caught.value.boundary == HardStopKind.ELECTRONIC_SIGNATURE.value


async def test_a_signature_upload_slot_refuses_a_file_too(harness, server):
    """An upload asking for a signed copy of something is no more automatable
    than a signature box, so `attach_file` refuses on the same terms."""
    url = server.page("/disguised", DISGUISED_FIELDS_HTML)
    async with await harness.open(url) as session:
        slot = _by_name(await session.read_fields(), "signature_upload")

        assert slot.human_only_boundary is HardStopKind.ELECTRONIC_SIGNATURE

        with pytest.raises(HumanOnlyFieldError):
            await session.attach_file(
                slot.handle, filename="signed.pdf", content=b"%PDF-1.4"
            )


async def test_ordinary_fields_on_the_same_form_are_still_fillable(harness, server):
    """The refusal is per field, not per page: a form with a signature box on
    it is not a form where nothing may be answered."""
    url = server.page("/sign", SIGNATURE_FORM_HTML)
    async with await harness.open(url) as session:
        name = _by_name(await session.read_fields(), "full_name")

        await session.fill(name.handle, "Ada Lovelace")

        assert _by_name(await session.read_fields(), "full_name").value == (
            "Ada Lovelace"
        )
