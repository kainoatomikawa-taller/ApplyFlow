"""A static guard on request URLs: no personal data in a path or query string.

Why URLs get their own rule
---------------------------
A query string is the least private part of a request. Unlike a body or a
header it is recorded by default, in places this application does not own and
cannot purge: web-server and proxy access logs, CDN logs, browser history,
and the `Referer` header the browser hands to whatever third party a page
links out to. Encrypting a column at rest (Epic 07) buys nothing if the same
address is sitting in plaintext in an ingress log.

So sensitive identifiers travel in the body or in a header — for this app
that mostly means "not at all", because it is single-user and the candidate's
identity comes from the verified bearer token.

What is checked
---------------
Both ends of the wire, since either alone can be wrong:

* every route parameter the API declares, path and query alike, read off the
  generated OpenAPI schema rather than by parsing decorators. The schema is
  the app's published URL surface by definition, it accounts for parameters
  contributed by dependencies and router-level includes, and it is a public
  contract — unlike the internal route objects, whose shape changes between
  FastAPI releases;
* the frontend API client's URL templates, since the backend cannot reject
  a parameter it never declared but a browser will still have recorded it.

Path parameters are checked as well as query ones. A path segment is just as
loggable as a query key, so `/applications/by-email/{email}` would be the
same leak with tidier syntax.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.interfaces.http.app import create_app

REPO = Path(__file__).resolve().parents[3]

#: Substrings that make a URL parameter name a leak. Prefix/suffix matching,
#: so `candidate_email` and `email` are both caught.
#:
#: `name` is not here: it matches `company_name`, `role_title`-adjacent names,
#: and `source_name`, none of which are personal. A candidate's name in a URL
#: would be `full_name` or `candidate_name`, both of which are.
PII_URL_FRAGMENTS: tuple[str, ...] = (
    "email",
    "phone",
    "full_name",
    "candidate_name",
    "first_name",
    "last_name",
    "street_address",
    "address_line",
    "postal_code",
    "zip_code",
    "date_of_birth",
    "ssn",
    "national_id",
    "citizenship",
    "visa",
    "gender",
    "race",
    "ethnicity",
    "veteran",
    "disability",
    "password",
    "token",
    "secret",
    "api_key",
)


def _offending_fragment(name: str) -> str | None:
    lowered = name.lower()
    for fragment in PII_URL_FRAGMENTS:
        if fragment in lowered:
            return fragment
    return None


_URL_PARAMETER_LOCATIONS = frozenset({"query", "path"})


def _url_parameters(spec: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Every (method, path, parameter name) that travels in the URL."""
    found: list[tuple[str, str, str]] = []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters", []):
                if parameter.get("in") in _URL_PARAMETER_LOCATIONS:
                    found.append((method.upper(), path, parameter["name"]))
    return found


def test_no_route_declares_a_pii_bearing_path_or_query_parameter() -> None:
    parameters = _url_parameters(create_app().openapi())

    problems = [
        f"{method} {path} takes {name!r} in the URL (matched {fragment!r})"
        for method, path, name in parameters
        if (fragment := _offending_fragment(name)) is not None
    ]

    assert not problems, (
        "Sensitive identifiers must arrive in the request body or a header, "
        "never in a path or query string — a URL is recorded by proxies, "
        "access logs, browser history and Referer headers this app does not "
        "control.\n  " + "\n  ".join(problems)
    )


def test_the_route_guard_reads_the_real_url_surface() -> None:
    """Proves the check is looking at something. A guard whose extraction
    silently returned nothing — a schema-shape change, a renamed key — would
    pass forever on an app full of leaks, which is exactly what happened while
    this file was being written against FastAPI's internal route objects."""
    parameters = _url_parameters(create_app().openapi())
    names = {name for _, _, name in parameters}

    # A representative query parameter, a representative path parameter, and
    # enough breadth to show the whole app was walked rather than one router.
    assert {"limit", "open_only"} <= names
    assert {"application_id", "job_posting_id", "review_id"} <= names
    assert len({path for _, path, _ in parameters}) > 10

    # And the matcher itself still fires on the name this task removed.
    assert _offending_fragment("candidate_email") == "email"
    assert _offending_fragment("limit") is None


# ---- The frontend half ----------------------------------------------------

#: Matches a template literal used as a request path, capturing what precedes
#: any query string: `` `/api/applications?candidate_email=${...}` ``.
_TEMPLATE_URL_RE = re.compile(r"`(/[^`]*)`")


def _frontend_request_urls() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for path in sorted((REPO / "frontend" / "src").rglob("*.ts")):
        for match in _TEMPLATE_URL_RE.finditer(path.read_text(encoding="utf-8")):
            found.append((path, match.group(1)))
    for path in sorted((REPO / "frontend" / "src").rglob("*.tsx")):
        for match in _TEMPLATE_URL_RE.finditer(path.read_text(encoding="utf-8")):
            found.append((path, match.group(1)))
    return found


def test_the_frontend_puts_no_pii_in_a_request_url() -> None:
    urls = _frontend_request_urls()
    assert urls, "expected to find request URLs in the frontend client"

    problems: list[str] = []
    for path, url in urls:
        fragment = _offending_fragment(url)
        if fragment is not None:
            problems.append(f"{path.relative_to(REPO)}: {url!r} contains {fragment!r}")

    assert not problems, (
        "The frontend must not build a URL containing personal data — the "
        "browser records it in history and may send it on in a Referer, "
        "whatever the backend does with it.\n  " + "\n  ".join(problems)
    )


def test_the_frontend_guard_would_catch_a_pii_url() -> None:
    """The regression this replaces: `listApplications` used to interpolate the
    candidate's address into the query string."""
    assert (
        _offending_fragment("/api/applications?candidate_email=${encoded}") == "email"
    )
    assert _offending_fragment("/api/tracked-applications?open_only=true") is None
