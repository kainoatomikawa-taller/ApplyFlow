"""Page observation — the in-page passes behind `read_boundary_signals()`
and `read_submit_controls()`.

(The pass behind `read_page_signals()`, which feeds `HardStopDetector`, is
its own module — `page_signals`. Two readings, two judges: see
`BrowserSessionPort`.)

Two jobs that both look at the page as a whole rather than at its fields,
kept beside `field_discovery` because they share its ground rules: one
`evaluate()` per frame (so a mutating page cannot produce a half-and-half
reading), everything coerced on the Python side, and nothing about *what
any of it means* decided here.

That last one is the load-bearing rule for the signals pass. Which frame
URL indicates a CAPTCHA, which phrase indicates a signature request — all
of that is domain policy (`detect_application_boundaries`). This module
collects tokens, URLs and text without a single rule about them, so a new
detection rule never requires touching the browser layer, and a rule can
never end up living in two places that disagree.

The submit pass is the opposite kind of narrow: it is the *only* place in
this harness that can hand back something pressable, so it enumerates
exactly the controls that send a form and nothing else. A "Save draft" or
"Add another employer" button is not returned, because the sole thing a
caller may obtain from here is a way to submit the application.
"""

from __future__ import annotations

from typing import Any

from src.application.ports.browser_automation_port import SubmitControl
from src.domain.value_objects.page_signals import PageSignals

#: How much visible text is kept per frame, and in total. Detection reads
#: phrases, not documents; a job description can run to tens of thousands
#: of characters and carrying it around would cost far more than it says.
MAX_FRAME_TEXT = 8_000
MAX_TOTAL_TEXT = 24_000

#: How many distinct markup tokens are kept. Generous enough for a real
#: ATS page (a few hundred), bounded so a generated-class-name framework
#: cannot turn one observation into a megabyte.
MAX_MARKERS = 600

#: Evaluated in each frame. Returns the frame's visible text, the URLs of
#: the scripts it loaded, and every `id`/`class` token on it.
#:
#: Named for the judge it feeds rather than for the page it reads, because
#: `page_signals.PAGE_SIGNALS_JS` is the *other* in-page pass — the one
#: `HardStopDetector` reads (see `BrowserSessionPort`, "Two readings, two
#: judges"). One importer holds both, so they cannot share a name.
#:
#: The two limits are substituted rather than interpolated: the source is
#: full of braces and percent-free JavaScript, and neither an f-string nor
#: `%`-formatting can be applied to it without escaping the whole thing.
BOUNDARY_SIGNALS_JS = """
() => {
  const MAX_TEXT = __MAX_TEXT__;
  const MAX_MARKERS = __MAX_MARKERS__;

  const text = ((document.body && document.body.innerText) || '')
    .replace(/\\s+/g, ' ')
    .trim()
    .slice(0, MAX_TEXT);

  const scriptUrls = Array.from(document.scripts || [])
    .map((script) => script.src || '')
    .filter(Boolean);

  const markers = new Set();
  const elements = document.querySelectorAll('[id], [class]');
  for (const element of elements) {
    if (markers.size >= MAX_MARKERS) break;
    const id = element.getAttribute('id');
    if (id) markers.add(id.trim());
    const className =
      typeof element.className === 'string'
        ? element.className
        : (element.getAttribute('class') || '');
    for (const token of className.split(/\\s+/)) {
      if (token) markers.add(token);
    }
  }

  return { text, scriptUrls, markers: Array.from(markers).slice(0, MAX_MARKERS) };
}
""".replace("__MAX_TEXT__", str(MAX_FRAME_TEXT)).replace(
    "__MAX_MARKERS__", str(MAX_MARKERS)
)


#: The CSS selector submit-control handles are resolved against. The pass
#: below MUST enumerate exactly this selector, in document order, because a
#: handle's index is its position in that enumeration.
SUBMIT_SELECTOR = "button, input[type=submit], input[type=image]"

#: Evaluated in each frame; returns one entry per control that would send
#: the form, carrying its index in `SUBMIT_SELECTOR`'s enumeration.
#:
#: The type rule is HTML's own: a `<button>` inside a form with no `type`
#: attribute is a submit button. A `<button type="button">` is not, and is
#: skipped — it is a "add another employer", a "cancel", or a widget, and
#: this call must never be a way to press one of those.
SUBMIT_DISCOVERY_JS = """
() => {
  const SELECTOR = 'button, input[type=submit], input[type=image]';
  const MAX_LABEL_LENGTH = 120;

  const clean = (text) =>
    (text || '').replace(/\\s+/g, ' ').trim().slice(0, MAX_LABEL_LENGTH);

  const isVisible = (el) => {
    const style = el.ownerDocument.defaultView.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const submits = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'input') {
      const type = String(el.type || '').toLowerCase();
      return type === 'submit' || type === 'image';
    }
    // A <button> with no type attribute defaults to submit, but only
    // inside a form; a loose one submits nothing.
    const declared = (el.getAttribute('type') || '').toLowerCase();
    if (declared === 'submit') return true;
    return declared === '' && el.form !== null;
  };

  const labelFor = (el) =>
    clean(el.getAttribute('aria-label'))
    || clean(el.tagName.toLowerCase() === 'input' ? el.value : el.innerText)
    || clean(el.getAttribute('title'))
    || clean(el.getAttribute('name'))
    || clean(el.getAttribute('id'));

  const controls = [];
  const found = document.querySelectorAll(SELECTOR);
  for (let index = 0; index < found.length; index += 1) {
    const el = found[index];
    if (el.disabled === true) continue;
    if (!submits(el)) continue;
    if (!isVisible(el)) continue;
    const tag = el.tagName.toLowerCase();
    controls.push({
      index,
      label: labelFor(el),
      signature: [
        tag,
        String(el.type || '').toLowerCase(),
        el.getAttribute('name') || '',
        el.getAttribute('id') || '',
        labelFor(el),
      ].join('|'),
    });
  }
  return controls;
}
"""

#: Re-derives the `signature` recorded above for one control. MUST stay
#: equivalent to the expression in `SUBMIT_DISCOVERY_JS`: the two are
#: compared before a press, and a divergence would either refuse every
#: submission or stop catching a page that moved its buttons around.
SUBMIT_SIGNATURE_JS = """
(el) => {
  const MAX_LABEL_LENGTH = 120;
  const clean = (text) =>
    (text || '').replace(/\\s+/g, ' ').trim().slice(0, MAX_LABEL_LENGTH);
  const label =
    clean(el.getAttribute('aria-label'))
    || clean(el.tagName.toLowerCase() === 'input' ? el.value : el.innerText)
    || clean(el.getAttribute('title'))
    || clean(el.getAttribute('name'))
    || clean(el.getAttribute('id'));
  return [
    el.tagName.toLowerCase(),
    String(el.type || '').toLowerCase(),
    el.getAttribute('name') || '',
    el.getAttribute('id') || '',
    label,
  ].join('|');
}
"""


def to_submit_control(handle: str, raw: dict[str, Any]) -> SubmitControl:
    """Build a `SubmitControl` from one discovery entry."""
    return SubmitControl(handle=handle, label=str(raw.get("label", "")))


def build_page_signals(
    *,
    url: str,
    frame_urls: tuple[str, ...],
    frame_payloads: tuple[dict[str, Any], ...],
) -> PageSignals:
    """Fold the per-frame observations into one `PageSignals`.

    Frames are merged rather than kept apart because the detection rules
    ask "does this page carry X", and on a real ATS page the form, the
    challenge widget and the consent text routinely live in three
    different frames. Every value is coerced here: the payloads come from
    JavaScript running against a page the portal controls.
    """
    texts: list[str] = []
    script_urls: list[str] = []
    markers: list[str] = []
    seen_markers: set[str] = set()

    for payload in frame_payloads:
        text = str(payload.get("text", "")).strip()
        if text:
            texts.append(text)
        for script_url in payload.get("scriptUrls") or ():
            script_urls.append(str(script_url))
        for marker in payload.get("markers") or ():
            token = str(marker).strip()
            if token and token not in seen_markers and len(markers) < MAX_MARKERS:
                seen_markers.add(token)
                markers.append(token)

    return PageSignals(
        url=url,
        visible_text=" ".join(texts)[:MAX_TOTAL_TEXT],
        frame_urls=frame_urls,
        script_urls=tuple(dict.fromkeys(script_urls)),
        element_markers=tuple(markers),
    )
