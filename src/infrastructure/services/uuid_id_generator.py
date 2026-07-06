"""UUID implementation of the IdGeneratorPort."""

from __future__ import annotations

import uuid

from src.application.ports.id_generator_port import IdGeneratorPort


class UuidIdGenerator(IdGeneratorPort):
    def new_id(self) -> str:
        return str(uuid.uuid4())
