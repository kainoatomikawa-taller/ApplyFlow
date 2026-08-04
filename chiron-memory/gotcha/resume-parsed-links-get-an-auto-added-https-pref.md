---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-90
type: gotcha
title: Résumé-parsed links get an auto-added "https://" prefix when the résumé printed a bare…
tags: [gotcha]
created: 2026-08-04
resource: src/application/use_cases/parse_resume.py / src/infrastructure/llm/llm_resume_parser.py.
---
Résumé-parsed links get an auto-added "https://" prefix when the résumé printed a bare host (e.g. "github.com/alexellis"), since that's still a valid URL statement — but anything else not URL-shaped after that is dropped entirely rather than guessed at, because ProfileLinks rejects a scheme-less value.

## Where
src/application/use_cases/parse_resume.py / src/infrastructure/llm/llm_resume_parser.py.
