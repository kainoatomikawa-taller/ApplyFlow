---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-93
type: config
title: Browser automation runs headless by default (`browser_headless
tags: [config]
created: 2026-08-04
resource: src/infrastructure/config.py, src/infrastructure/browser_automation/playwright_browser_automation.py.
---
Browser automation runs headless by default (`browser_headless: bool = True`); setting `BROWSER_HEADLESS=false` in .env.local opens a real visible Playwright window so a user can watch autofill navigate/click/type live.

## Why
Useful for debugging odd portal behavior, but slower and steals window focus, so it's meant as a debugging mode rather than the default running mode.

## Where
src/infrastructure/config.py, src/infrastructure/browser_automation/playwright_browser_automation.py.
