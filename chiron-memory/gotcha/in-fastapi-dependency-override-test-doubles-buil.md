---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-7
type: gotcha
title: In FastAPI dependency-override test doubles, building per-value route closures with…
tags: [gotcha]
created: 2026-08-04
resource: tests/interfaces/http/test_data_rights_controller.py.
---
In FastAPI dependency-override test doubles, building per-value route closures with `lambda v=value: v` makes FastAPI interpret the parameter as a query parameter instead of a fixed closure value; use a proper closure or functools.partial instead

## Where
tests/interfaces/http/test_data_rights_controller.py.
