"""CLI entry point (interfaces layer).

Demonstrates driving a use case from a non-HTTP adapter. Like the HTTP
controllers, it is thin: parse args -> call use case -> print output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from src.application.dtos.data_rights_dtos import (
    DataSubjectRef,
    ErasureRequestInput,
)
from src.application.dtos.job_application_dtos import CreateJobApplicationInput
from src.application.dtos.job_ingestion_dtos import (
    IngestAggregatorJobsInput,
    IngestBoardJobsInput,
    TargetBoard,
)
from src.application.dtos.llm_dtos import LlmCompletionInput
from src.application.exceptions import ErasureNotAcknowledgedError
from src.application.ports.llm_client_port import LlmTaskType
from src.application.use_cases.create_job_application import (
    CreateJobApplication,
)
from src.application.use_cases.erase_user_data import EraseUserData
from src.application.use_cases.export_user_data import ExportUserData
from src.application.use_cases.get_llm_completion import GetLlmCompletion
from src.application.use_cases.ingest_aggregator_jobs import IngestAggregatorJobs
from src.application.use_cases.ingest_board_jobs import IngestBoardJobs
from src.domain.services.ats_board_locator import identify_ats_board
from src.domain.value_objects.ats_provider import AtsProvider
from src.infrastructure.ats_boards.ashby_board_client import AshbyBoardClient
from src.infrastructure.ats_boards.greenhouse_board_client import GreenhouseBoardClient
from src.infrastructure.ats_boards.lever_board_client import LeverBoardClient
from src.infrastructure.config import get_settings
from src.infrastructure.job_aggregators.adzuna_client import AdzunaJobAggregatorClient
from src.infrastructure.llm.anthropic_client import AnthropicLlmClient
from src.infrastructure.observability import configure_logging
from src.infrastructure.persistence.consent_repository_impl import (
    SqlAlchemyConsentRepository,
)
from src.infrastructure.persistence.database import async_session_factory
from src.infrastructure.persistence.job_application_repository_impl import (
    SqlAlchemyJobApplicationRepository,
)
from src.infrastructure.persistence.job_posting_repository_impl import (
    SqlAlchemyJobPostingRepository,
)
from src.infrastructure.persistence.personal_data_store_impl import (
    SqlAlchemyPersonalDataStore,
)
from src.infrastructure.security.sensitive_access import sensitive_data_access
from src.infrastructure.services.uuid_id_generator import UuidIdGenerator
from src.infrastructure.storage.local_file_storage import LocalFileStorage


async def _create(args: argparse.Namespace) -> None:
    # An authorized decryption path (Epic 07): the local operator running this
    # command supplied the address themselves, and the use case reads back the
    # row it wrote. The subject is the address rather than a user id because the
    # CLI has no authenticated session — it is trusted by virtue of being a
    # local process, and the scope records what it acted on.
    with sensitive_data_access(
        subject=args.email, reason="applyflow create (local CLI operator)"
    ):
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


async def _ingest_adzuna(args: argparse.Namespace) -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        use_case = IngestAggregatorJobs(
            repository=SqlAlchemyJobPostingRepository(session),
            aggregator=AdzunaJobAggregatorClient(settings),
            id_generator=UuidIdGenerator(),
        )
        output = await use_case.execute(
            IngestAggregatorJobsInput(
                keywords=args.keywords,
                location=args.location,
                max_pages=args.max_pages,
            )
        )
        print(
            f"Fetched {output.pages_fetched} page(s), saw "
            f"{output.listings_seen} listing(s): ingested "
            f"{output.ingested_count}, skipped "
            f"{output.skipped_duplicate_count} duplicate(s)"
        )


def _parse_board(company: str, locator: str) -> TargetBoard:
    """One `--board COMPANY LOCATOR` pair, where the locator is either the
    board's URL or `provider:token`.

    Accepting the URL is the point: it is what a candidate already has in front
    of them from the company's careers page, and `identify_ats_board` reads the
    provider and token straight out of it — no search call, no guessing.
    """
    company = company.strip()
    locator = locator.strip()
    if not company:
        raise SystemExit("--board needs a company name as its first value")

    reference = identify_ats_board(locator)
    if reference is not None:
        return TargetBoard(
            company=company,
            provider=reference.provider,
            board_token=reference.board_token,
        )

    if locator.lower().startswith(("http://", "https://")):
        raise SystemExit(
            f"{locator!r} is not a recognized Greenhouse, Lever or Ashby board "
            "URL. Expected something like https://boards.greenhouse.io/stripe, "
            "https://jobs.lever.co/acme or "
            "https://jobs.ashbyhq.com/acme — or pass 'provider:token' instead."
        )

    provider_text, separator, token = locator.partition(":")
    if not separator or not token.strip():
        raise SystemExit(
            f"Could not read a board from {locator!r}. Pass the board URL, or "
            "'provider:token' (e.g. greenhouse:stripe)."
        )
    try:
        provider = AtsProvider(provider_text.strip().lower())
    except ValueError:
        supported = ", ".join(provider.value for provider in AtsProvider)
        raise SystemExit(
            f"Unknown ATS provider {provider_text!r}. Supported: {supported}."
        ) from None
    return TargetBoard(company=company, provider=provider, board_token=token.strip())


def _boards_from_file(path: str) -> list[TargetBoard]:
    """Read a target list of `Company,locator` lines.

    A file rather than a database table: the list of companies a candidate is
    targeting is theirs to edit, changes constantly, and is worth nothing to
    anyone else. A text file they can keep in version control answers that better
    than a schema, and nothing else in the app needs to read it.
    """
    boards: list[TargetBoard] = []
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            company, separator, locator = line.partition(",")
            if not separator:
                raise SystemExit(
                    f"{path}:{number}: expected 'Company,board-url-or-provider:token'"
                )
            boards.append(_parse_board(company, locator))
    return boards


async def _ingest_board(args: argparse.Namespace) -> None:
    settings = get_settings()
    boards = [_parse_board(company, locator) for company, locator in args.board or []]
    if args.boards_file:
        boards.extend(_boards_from_file(args.boards_file))
    if not boards:
        raise SystemExit("Pass at least one --board or a --boards-file.")

    async with async_session_factory() as session:
        use_case = IngestBoardJobs(
            repository=SqlAlchemyJobPostingRepository(session),
            board_clients={
                AtsProvider.GREENHOUSE: GreenhouseBoardClient(settings),
                AtsProvider.LEVER: LeverBoardClient(settings),
                AtsProvider.ASHBY: AshbyBoardClient(settings),
            },
            id_generator=UuidIdGenerator(),
        )
        output = await use_case.execute(IngestBoardJobsInput(boards=tuple(boards)))

    for result in output.results:
        if result.error is not None:
            print(
                f"  {result.company} ({result.provider.value}:"
                f"{result.board_token}) FAILED: {result.error}"
            )
            continue
        print(
            f"  {result.company} ({result.provider.value}:{result.board_token}): "
            f"saw {result.postings_seen}, ingested {result.ingested_count}, "
            f"skipped {result.skipped_duplicate_count} duplicate(s)"
        )
    print(
        f"Read {output.boards_read}/{len(output.results)} board(s), saw "
        f"{output.postings_seen} posting(s): ingested {output.ingested_count}, "
        f"skipped {output.skipped_duplicate_count} duplicate(s)"
    )
    if output.failed_boards:
        # Non-zero exit so a scripted run notices, even though the rest of the
        # boards were ingested successfully.
        raise SystemExit(f"{len(output.failed_boards)} board(s) could not be read")


async def _export_data(args: argparse.Namespace) -> None:
    """Write a complete portable copy of a user's data to stdout as JSON.

    An authorized decryption path (Epic 07) for the same reason `_create` is: the
    operator running this command locally is acting on their own data. The scope
    names the subject it acts for, and the reason says which right is being
    exercised, so an audit of `sensitive_access.py`'s call sites reads as a list
    of purposes rather than a list of `True`s.

    A CLI command as well as an endpoint because a data-subject request has to be
    answerable when the API cannot answer it — no valid token, a frontend that is
    down, or an operator handling a request that arrived by email. That is the
    ordinary shape of a subject access request, and having only an authenticated
    endpoint would make it the one case the design cannot serve.

    JSON, so the copy is machine-readable in the sense GDPR Art. 20 means.
    `--output` writes it to a file and is the option to prefer for two reasons:
    with `DEBUG` on, SQLAlchemy echoes every statement to stdout and would
    interleave itself into a redirected document; and printing a person's entire
    record to a terminal puts it in a scrollback buffer, which is the one output
    here as sensitive as the database itself.
    """
    with sensitive_data_access(
        subject=args.user_id,
        reason="applyflow export-data (subject access request, local CLI)",
    ):
        async with async_session_factory() as session:
            use_case = ExportUserData(
                store=SqlAlchemyPersonalDataStore(
                    session, LocalFileStorage(Path(get_settings().resume_storage_dir))
                ),
                consent_repository=SqlAlchemyConsentRepository(session),
            )
            output = await use_case.execute(
                DataSubjectRef(user_id=args.user_id, email=args.email),
                generated_at=datetime.now(UTC),
            )
    document = json.dumps(asdict(output), indent=2, default=str)
    if args.output:
        # Written after the access scope has closed, so the plaintext is held
        # only as long as it takes to serialize it.
        Path(args.output).write_text(document, encoding="utf-8")
        # The path and the counts, never the contents — the same rule the HTTP
        # controller logs by.
        print(
            f"Wrote {len(output.categories)} categories "
            f"({sum(c.record_count for c in output.categories)} records) "
            f"to {args.output}"
        )
        return
    print(document)


async def _erase_data(args: argparse.Namespace) -> None:
    """Erase everything erasable about a user, and print the receipt.

    `--confirm` is required and unabbreviated on purpose. A shell history is one
    arrow-key away from re-running an irreversible command, and the HTTP endpoint
    at least involves a client someone wrote deliberately.

    The flag is still passed through to the use case rather than checked here, so
    the refusal stays in one place for every adapter; what this function adds is
    presenting it as a message and an exit code instead of a traceback.
    """
    with sensitive_data_access(
        subject=args.user_id,
        reason="applyflow erase-data (erasure request, local CLI)",
    ):
        async with async_session_factory() as session:
            use_case = EraseUserData(
                store=SqlAlchemyPersonalDataStore(
                    session, LocalFileStorage(Path(get_settings().resume_storage_dir))
                ),
                consent_repository=SqlAlchemyConsentRepository(session),
            )
            try:
                output = await use_case.execute(
                    ErasureRequestInput(
                        subject=DataSubjectRef(user_id=args.user_id, email=args.email),
                        requested_at=datetime.now(UTC),
                        acknowledged=args.confirm,
                        policy_version=get_settings().privacy_policy_version,
                        reason=args.reason,
                    )
                )
            except ErasureNotAcknowledgedError as exc:
                raise SystemExit(f"{exc} Re-run with --confirm.") from exc
            print(json.dumps(asdict(output), indent=2, default=str))


async def _llm_ping(args: argparse.Namespace) -> None:
    use_case = GetLlmCompletion(llm_client=AnthropicLlmClient(get_settings()))
    output = await use_case.execute(
        LlmCompletionInput(prompt=args.prompt, task_type=LlmTaskType(args.task_type))
    )
    print(output.text)


def main() -> None:
    # Before anything can log. The CLI owns its stdout, so unlike the API this
    # entry point does want a handler installed (Epic 07 — see
    # src/infrastructure/observability/pii_redaction.py).
    configure_logging()

    parser = argparse.ArgumentParser(prog="applyflow")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create a job application")
    create.add_argument("--email", required=True)
    create.add_argument("--company", required=True)
    create.add_argument("--role", required=True)
    create.add_argument("--description", required=True)
    create.set_defaults(func=_create)

    ingest_adzuna = sub.add_parser(
        "ingest-adzuna", help="Fetch and persist job listings from Adzuna"
    )
    ingest_adzuna.add_argument("--keywords", required=True)
    ingest_adzuna.add_argument("--location", default=None)
    ingest_adzuna.add_argument("--max-pages", type=int, default=1)
    ingest_adzuna.set_defaults(func=_ingest_adzuna)

    ingest_board = sub.add_parser(
        "ingest-board",
        help=(
            "Read companies' own Greenhouse/Lever/Ashby boards directly. "
            "Unauthenticated and unmetered — no search-API quota is used."
        ),
    )
    ingest_board.add_argument(
        "--board",
        action="append",
        nargs=2,
        metavar=("COMPANY", "URL_OR_PROVIDER:TOKEN"),
        help=(
            "Repeatable. e.g. --board Stripe https://boards.greenhouse.io/stripe "
            "or --board Ramp ashby:ramp"
        ),
    )
    ingest_board.add_argument(
        "--boards-file",
        default=None,
        help="File of 'Company,board-url-or-provider:token' lines; # comments allowed.",
    )
    ingest_board.set_defaults(func=_ingest_board)

    llm_ping = sub.add_parser(
        "llm-ping", help="Send one prompt through the LLM integration layer"
    )
    llm_ping.add_argument("--prompt", required=True)
    llm_ping.add_argument(
        "--task-type",
        choices=[t.value for t in LlmTaskType],
        default=LlmTaskType.EXTRACTION.value,
        help="Task intent, not a model name — the LLM layer picks the model tier",
    )
    llm_ping.set_defaults(func=_llm_ping)

    # -- Data-subject rights. Both take the subject as an argument rather than
    # inferring it: this application has one user today, but a command that
    # erases "the account" without naming it is a command nobody can review in a
    # shell history. `--email` is optional and reaches the one store that
    # predates the account model (see the `legacy_applications` category); the
    # output says so when it is absent rather than reporting an empty result.
    export_data = sub.add_parser(
        "export-data",
        help="Write a portable copy of a user's data to stdout (GDPR Art. 15/20)",
    )
    export_data.add_argument("--user-id", required=True)
    export_data.add_argument(
        "--email",
        default=None,
        help="Reaches records filed under an address rather than an account id",
    )
    export_data.add_argument(
        "--output",
        default=None,
        help=(
            "Write the copy to this file instead of stdout. Preferred: with "
            "DEBUG on, SQL echo shares stdout and would corrupt a redirect."
        ),
    )
    export_data.set_defaults(func=_export_data)

    erase_data = sub.add_parser(
        "erase-data",
        help="Erase everything erasable about a user (GDPR Art. 17) — irreversible",
    )
    erase_data.add_argument("--user-id", required=True)
    erase_data.add_argument(
        "--email",
        default=None,
        help="Reaches records filed under an address rather than an account id",
    )
    erase_data.add_argument("--reason", default="")
    erase_data.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Without it the request is refused rather than run.",
    )
    erase_data.set_defaults(func=_erase_data)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
