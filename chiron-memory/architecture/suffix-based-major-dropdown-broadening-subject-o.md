---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-89
type: architecture
title: Suffix-based major-dropdown broadening (subject_option_matcher.py) prefers the longest…
tags: [architecture]
created: 2026-08-04
---
Suffix-based major-dropdown broadening (subject_option_matcher.py) prefers the longest matching trailing-word category run when more than one could apply — e.g. "Electrical and Computer Engineering" broadens to "Computer Engineering" rather than just "Engineering" when both are offered as dropdown options.
