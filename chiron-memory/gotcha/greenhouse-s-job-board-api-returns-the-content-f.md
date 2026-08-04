---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-79
type: gotcha
title: Greenhouse's job board API returns the `content` field HTML-escaped (e.g. `&lt;h2&gt;`),…
tags: [gotcha]
created: 2026-08-04
resource: src/infrastructure/ats_boards/html_to_text.py.
---
Greenhouse's job board API returns the `content` field HTML-escaped (e.g. `&lt;h2&gt;`), and html_to_text previously stripped tags first and unescaped afterward — the wrong order — which turned escaped tags back into literal visible `<h2>` markup in stored descriptions instead of removing them.

## Why
This was a pre-existing bug (not introduced during the board-ingest work) that silently corrupted every Greenhouse-sourced description, which matters because requirement extraction reads the description text.

## Learned
Fixed by unescaping first, then stripping tags (gated on the output still looking tag-shaped); also removed a redundant explicit `unescape()` call because Python's HTMLParser already converts character references via `convert_charrefs=True` by default, and calling unescape again was double-unescaping and corrupting doubly-escaped text.

## Where
src/infrastructure/ats_boards/html_to_text.py.
