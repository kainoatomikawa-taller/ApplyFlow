"""PageSignals — what a browser observed about the page it is parked on,
beyond the fields it can fill.

This exists because deciding whether an application page carries a
human-only check (see `ApplicationBoundary`) needs to look at more than the
form controls, and none of that looking may happen inside the browser
adapter. Detection rules are policy — which markers count as a CAPTCHA,
which phrases count as a signature request — and policy belongs in the
domain, where it can be read and exercised without a browser.

So the split is: the adapter *observes*, in generic terms it does not
interpret, and the domain *decides*. Everything here is deliberately
rule-free — a list of frame URLs, a list of CSS tokens, the visible text —
so that adding a detection rule never means changing the browser layer,
and a rule can never quietly live in two places.

Nothing here is a selector or a handle. A caller cannot act on any of it;
it is evidence, not an address.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PageSignals:
    """One observation of the loaded page, taken alongside a field read.

    Every field defaults to empty so a caller that could only gather some
    of it (a frame that detached mid-read, a page that refused to yield its
    text) still produces a usable observation rather than nothing at all.
    """

    #: The URL actually loaded when the observation was taken.
    url: str = ""
    #: The page's visible text, normalized and truncated. Truncation is the
    #: adapter's business; the rules below read phrases, not documents.
    visible_text: str = ""
    #: The `src` of every frame on the page, including nested ones. Third
    #: party challenge widgets are near-universally iframes, and the frame
    #: URL names the provider when nothing else on the page does.
    frame_urls: tuple[str, ...] = ()
    #: The `src` of every external script the page loaded. A challenge
    #: widget that has not painted yet has still fetched its script.
    script_urls: tuple[str, ...] = ()
    #: Deduplicated `id` and `class` tokens seen on the page. Generic on
    #: purpose: the adapter collects tokens without knowing which ones
    #: matter, so the domain owns the whole vocabulary.
    element_markers: tuple[str, ...] = field(default_factory=tuple)
