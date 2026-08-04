"""JobFunction — the kind of work a role is, as a family of roles.

Why function and not industry
-----------------------------
A candidate says "I want to do product" or "I want quant finance" far more readily
than they say "I want to work in fintech". Function is also the axis a posting's
text actually reveals: a job description says what you would be doing in every
paragraph, and mentions the employer's sector once, in the boilerplate.

Industry is a second, independent axis and is deliberately absent for now. The
field is named `function` rather than something vaguer precisely so that adding
industry later is an addition rather than a rename of a column candidates already
have data in.

Deliberately no `OTHER` member
------------------------------
An "other" bucket would be a value a posting could be classified *into*, and a
candidate could then select — which would filter to postings whose only shared
property is that nothing recognized them. `None` already carries the honest
meaning ("could not tell"), and under this domain's standing rule an unknown never
narrows anything.

Granularity
-----------
Coarse on purpose. These are the distinctions a candidate makes when deciding
which list to read, not a job-title ontology. `DATA_ANALYTICS` and `DATA_SCIENCE`
are separate because the day-to-day and the hiring bar differ, even though
employers use the words interchangeably; someone who wants either can select both.
"""

from __future__ import annotations

from enum import StrEnum


class JobFunction(StrEnum):
    SOFTWARE_ENGINEERING = "software_engineering"
    #: Analyst and business-intelligence work: reporting, dashboards, SQL.
    DATA_ANALYTICS = "data_analytics"
    #: Modelling and machine-learning work.
    DATA_SCIENCE = "data_science"
    PRODUCT_MANAGEMENT = "product_management"
    DESIGN = "design"
    #: Trading, research and quantitative modelling at a fund or desk.
    QUANTITATIVE_FINANCE = "quantitative_finance"
    INVESTMENT_BANKING = "investment_banking"
    CONSULTING = "consulting"
    #: Corporate finance and accounting, as distinct from markets work.
    FINANCE_ACCOUNTING = "finance_accounting"
    MARKETING = "marketing"
    SALES = "sales"
    OPERATIONS = "operations"
    #: Academic or industrial research, where the output is findings.
    RESEARCH = "research"
    #: Electrical, mechanical, and other non-software engineering.
    HARDWARE_ENGINEERING = "hardware_engineering"
    HUMAN_RESOURCES = "human_resources"
    LEGAL = "legal"
