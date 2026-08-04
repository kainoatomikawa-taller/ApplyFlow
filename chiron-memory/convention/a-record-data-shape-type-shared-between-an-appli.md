---
id: 12c5586a-5613-43e0-b8c1-f480bf046ae6-17
type: convention
title: A record/data-shape type shared between an application port and its DTOs is defined in…
tags: [convention]
created: 2026-08-04
resource: src/application/ports/personal_data_store_port.py and src/application/dtos/data_rights_dtos.py.
---
A record/data-shape type shared between an application port and its DTOs is defined in the DTOs module and imported by the port, not defined in the port module

## Why
defining it in the port caused a circular import between the port and the DTOs that use it

## Where
src/application/ports/personal_data_store_port.py and src/application/dtos/data_rights_dtos.py.
