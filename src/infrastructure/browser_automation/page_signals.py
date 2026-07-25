"""Page-signal collection — the in-page pass that reduces a live portal page
to the facts `HardStopDetector` reasons over.

Split from field discovery because the two answer different questions.
`FIELD_DISCOVERY_JS` asks "what can be filled here?"; this pass asks "what
kind of page is this?" — what it says, what it loads, and how its markup names
itself. A page with no fillable field at all still answers this one, and its
answer is frequently the whole story: an apply link that redirected to a login
screen has no form to discover and nothing left to say except its URL.

What the sweep collects, and what it refuses to decide
-----------------------------------------------------
Nothing here knows what a CAPTCHA is. The selector is structural (everything
in the document, capped) and the attributes are structural (`id`, `class`,
`name`, `title`, `data-*`), so the vocabulary that recognizes a vendor widget
stays in one place, in the domain, where it can be reviewed as a policy rather
than as a scraping detail. Infrastructure gathers; the domain judges. If that
boundary were blurred — a `[class*="captcha"]` selector here — the rules would
live in two layers and the JavaScript half would be the one nobody reviews.

Field-derived signals (labels, how many fields, how many password fields) are
NOT re-derived here. They come from the same `FIELD_DISCOVERY_JS` pass that
`read_fields()` uses, so the detector's view of the form is exactly the form
the harness would have filled — a second implementation of "which fields
count" would eventually disagree with the first, and the disagreement would
show up as a boundary check that passed on a form containing a password box.

Everything is bounded. A portal is untrusted input that can serve a
hundred-megabyte DOM, and these values get stored on a hand-off and returned
over an API.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from src.domain.value_objects.portal_page_signals import PortalPageSignals

#: Per-frame caps applied in the browser, before anything crosses the bridge.
_MAX_TEXT_LENGTH = 20_000
_MAX_SCRIPT_URLS = 120
_MAX_HINTS = 500
_MAX_ELEMENTS_SWEPT = 5_000

#: Whole-page caps applied on this side, after frames are combined.
_MAX_TOTAL_TEXT_LENGTH = 60_000
_MAX_TOTAL_HINTS = 1_500
_MAX_TOTAL_SCRIPT_URLS = 300
_MAX_FIELD_LABELS = 400

#: Evaluated in each frame. Returns the page-level half of the signals: what
#: the frame says, what it loads, and the markup names of what it contains.
PAGE_SIGNALS_JS = f"""
() => {{
  const MAX_TEXT_LENGTH = {_MAX_TEXT_LENGTH};
  const MAX_SCRIPT_URLS = {_MAX_SCRIPT_URLS};
  const MAX_HINTS = {_MAX_HINTS};
  const MAX_ELEMENTS = {_MAX_ELEMENTS_SWEPT};
  const MAX_HINT_LENGTH = 80;

  const clean = (text) => (text || '').replace(/\\s+/g, ' ').trim();

  const hints = new Set();
  const addHint = (value) => {{
    if (hints.size >= MAX_HINTS) return;
    const token = clean(value).toLowerCase();
    // Long values are page content (a JSON blob in a data attribute), not a
    // name a widget goes by, and the vocabulary only ever matches names.
    if (token && token.length <= MAX_HINT_LENGTH) hints.add(token);
  }};

  const elements = document.querySelectorAll('*');
  const sweptCount = Math.min(elements.length, MAX_ELEMENTS);
  for (let index = 0; index < sweptCount; index += 1) {{
    const el = elements[index];
    addHint(el.getAttribute('id'));
    addHint(el.getAttribute('name'));
    addHint(el.getAttribute('title'));
    const classList = el.classList ? Array.from(el.classList) : [];
    for (const token of classList) addHint(token);
    const attributes = el.attributes ? Array.from(el.attributes) : [];
    for (const attribute of attributes) {{
      // `data-*` is how widgets are mounted and configured, so both halves
      // matter: the attribute's name (data-sitekey) and its value.
      if (!attribute.name.startsWith('data-')) continue;
      addHint(attribute.name);
      addHint(attribute.value);
    }}
    if (hints.size >= MAX_HINTS) break;
  }}

  const scriptUrls = [];
  for (const script of document.querySelectorAll('script[src]')) {{
    if (scriptUrls.length >= MAX_SCRIPT_URLS) break;
    if (script.src) scriptUrls.push(script.src);
  }}

  // innerText rather than textContent: it is what a person can actually
  // read, so it excludes the <script> and <style> bodies that would
  // otherwise put every vendor's name into the page's "prose".
  const body = document.body;
  const text = clean(body ? body.innerText : '').slice(0, MAX_TEXT_LENGTH);

  return {{
    url: location.href,
    title: clean(document.title),
    text,
    scriptUrls,
    hints: Array.from(hints),
  }};
}}
"""


def to_page_signals(
    *,
    url: str,
    frame_urls: Iterable[str],
    frame_readings: Sequence[dict[str, Any]],
    field_entries: Iterable[dict[str, Any]],
) -> PortalPageSignals:
    """Combine per-frame readings and the field-discovery pass into one
    `PortalPageSignals`.

    Defensive about every value: `frame_readings` and `field_entries` come
    from JavaScript running in a page the portal controls, so nothing is
    trusted to be the type or the length it should be.

    `url` is the URL the browser reports for the page itself, passed in rather
    than taken from a frame reading — a frame can navigate between the
    evaluate and this call, and the landed URL is the one signal a hand-off
    quotes back to the candidate as "where automation stopped".
    """
    titles: list[str] = []
    texts: list[str] = []
    script_urls: list[str] = []
    hints: list[str] = []
    for reading in frame_readings:
        if not isinstance(reading, dict):  # pragma: no cover - defensive
            continue
        title = _as_text(reading.get("title"))
        if title:
            titles.append(title)
        text = _as_text(reading.get("text"))
        if text:
            texts.append(text)
        script_urls.extend(_as_texts(reading.get("scriptUrls")))
        hints.extend(_as_texts(reading.get("hints")))

    labels: list[str] = []
    password_count = 0
    fillable_count = 0
    for entry in field_entries:
        if not isinstance(entry, dict):  # pragma: no cover - defensive
            continue
        fillable_count += 1
        label = _as_text(entry.get("label"))
        if label:
            labels.append(label)
        # The discovery pass already normalized the control's type, and has
        # already dropped hidden, disabled, and read-only controls — so this
        # counts password fields the portal is actually presenting, not a
        # decoy left in the markup for a password manager.
        if _as_text(entry.get("type")).casefold() == "password":
            password_count += 1

    return PortalPageSignals(
        url=url,
        # The main document's title is the page's title; a frame's title is
        # rarely meaningful and never authoritative, but it costs nothing to
        # keep as prose the detector can match.
        title=" ".join(titles)[:_MAX_TOTAL_TEXT_LENGTH],
        text=" ".join(texts)[:_MAX_TOTAL_TEXT_LENGTH],
        frame_urls=_deduped(_as_texts(frame_urls), _MAX_TOTAL_HINTS),
        script_urls=_deduped(script_urls, _MAX_TOTAL_SCRIPT_URLS),
        element_hints=_deduped(hints, _MAX_TOTAL_HINTS),
        field_labels=tuple(labels[:_MAX_FIELD_LABELS]),
        password_field_count=password_count,
        fillable_field_count=fillable_count,
    )


def _as_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_texts(value: object) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        return []
    return [text for text in (_as_text(item) for item in value) if text]


def _deduped(values: Iterable[str], limit: int) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        if len(seen) >= limit:
            break
        seen.setdefault(value, None)
    return tuple(seen)
