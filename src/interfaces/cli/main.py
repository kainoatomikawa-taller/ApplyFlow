"""CLI entry point (interfaces layer).

Demonstrates driving a use case from a non-HTTP adapter. Like the HTTP
controllers, it is thin: parse args -> call use case -> print output.
"""

from __future__ import annotations

import argparse
import asyncio

from src.application.dtos.job_application_dtos import CreateJobApplicationInput
from src.application.dtos.llm_dtos import LlmCompletionInput
from src.application.use_cases.create_job_application import (
    CreateJobApplication,
)
from src.application.use_cases.get_llm_completion import GetLlmCompletion
from src.infrastructure.config import get_settings
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient
from src.infrastructure.persistence.database import async_session_factory
from src.infrastructure.persistence.job_application_repository_impl import (
    SqlAlchemyJobApplicationRepository,
)
from src.infrastructure.services.uuid_id_generator import UuidIdGenerator


async def _create(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        use_case = CreateJobApplication(
            repository=SqlAlchemyJobApplicationRepository(session),
            id_generator=UuidIdGenerator(),
        )
        output = await use_case.execute(
            CreateJobApplicationInput(
                candidate_email=args.email,
                company_name=args.company,
                role_title=args.role,
                job_description=args.description,
            )
        )
        print(f"Created application {output.id} ({output.status})")


async def _llm_ping(args: argparse.Namespace) -> None:
    use_case = GetLlmCompletion(llm_client=AnthropicLlmClient(get_settings()))
    output = await use_case.execute(LlmCompletionInput(prompt=args.prompt))
    print(output.text)


def main() -> None:
    parser = argparse.ArgumentParser(prog="applyflow")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create a job application")
    create.add_argument("--email", required=True)
    create.add_argument("--company", required=True)
    create.add_argument("--role", required=True)
    create.add_argument("--description", required=True)
    create.set_defaults(func=_create)

    llm_ping = sub.add_parser(
        "llm-ping", help="Send one prompt through the LLM integration layer"
    )
    llm_ping.add_argument("--prompt", required=True)
    llm_ping.set_defaults(func=_llm_ping)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
