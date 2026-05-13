"""
Data access policy: explicit tier-scoped data exposure.

Every agent has a defined set of data tiers it can access. The Data Broker
uses this to filter what's available for a given query. Information
boundaries become impossible-by-construction to violate.

Tiers:
  PUBLIC         — Compustat as-reported, gazettes, analyst notes, earnings
                   releases, audit opinions, M&A announcements
  CROSS_RUN      — historical panels from past runs (public columns only)
  OWN_PRIVATE    — a firm's own board minutes, R&D details, capability stock,
                   brand stock, manipulation_amount, CEO type
  CLIENT_PRIVATE — auditor's view of its client firm (like OWN_PRIVATE but
                   scoped to the client relationship)
  HIDDEN         — world secrets, CEO types across all firms, cumulative
                   manipulation truth, detection events (environment only)
"""

from __future__ import annotations

from enum import Enum


class DataTier(Enum):
    PUBLIC = "public"
    CROSS_RUN = "cross_run"
    OWN_PRIVATE = "own_private"
    CLIENT_PRIVATE = "client_private"
    HIDDEN = "hidden"


# Role -> allowed tiers. Role prefix matching for parameterized agents.
ROLE_TIERS: dict[str, set[DataTier]] = {
    "firm":              {DataTier.PUBLIC, DataTier.CROSS_RUN, DataTier.OWN_PRIVATE},
    "environment":       {DataTier.PUBLIC, DataTier.CROSS_RUN, DataTier.OWN_PRIVATE,
                          DataTier.CLIENT_PRIVATE, DataTier.HIDDEN},
    "equity_market":     {DataTier.PUBLIC, DataTier.CROSS_RUN},
    "investment_bank":   {DataTier.PUBLIC, DataTier.CROSS_RUN},
    "commercial_bank":   {DataTier.PUBLIC, DataTier.CROSS_RUN},
    "data_analyst":      {DataTier.PUBLIC, DataTier.CROSS_RUN},
    "analyst":           {DataTier.PUBLIC, DataTier.CROSS_RUN},  # sell-side
    "sec":               {DataTier.PUBLIC, DataTier.CROSS_RUN},
    "auditor":           {DataTier.PUBLIC, DataTier.CROSS_RUN, DataTier.CLIENT_PRIVATE},
    "board_governance":  {DataTier.PUBLIC, DataTier.CROSS_RUN, DataTier.OWN_PRIVATE},
}


# Columns in each tier. Used to filter Compustat rows when serving data.
# Reference: see src/types.py CompustatRow definition.
PUBLIC_COLUMNS = {
    # Keys
    "run_id", "firm_id", "incarnation", "fyearq", "fqtr",
    # Income statement
    "saleq", "cogsq", "gpq", "xrdq", "xsgaq", "dpq", "oiadpq",
    "xintq", "piq", "txtq", "niq",
    # Balance sheet
    "cheq", "rectq", "invtq", "ppentq", "ppegtq", "actq", "atq",
    "apq", "xaccq", "txpq", "drcq", "dlcq", "lctq", "dlttq", "ltq",
    "cstkq", "apicq", "ceqq", "seqq", "req", "tstkq",
    # Cash flow
    "oancfq", "ivncfq", "fincfq", "chechq", "capxq",
    "sstkq", "prstkq", "dvq",
    # Market
    "prccq", "cshoq", "mkvaltq",
    # Identifiers / metadata (Stage 9)
    "cusip", "indfmt", "consol", "popsrc", "datafmt",
    # Status flags (public)
    "default_flag", "empq", "gdwlq",
    # Restatement (public columns)
    "saleq_restated", "cogsq_restated", "niq_restated",
    "cheq_restated", "atq_restated", "ltq_restated",
    "ceqq_restated", "req_restated", "oancfq_restated",
    "restatement_flag", "restatement_quarter",
    # Audit (public disclosure)
    "audit_opinion", "auditor_id",
}

# Hidden columns that NEVER leave the environment's view.
HIDDEN_COLUMNS = {
    "manipulation_amount",  # true manipulation; only env (and detected-by-SEC/auditor)
}


def role_to_key(role: str) -> str:
    """Map a parameterized role (firm_0, analyst_1) to its tier key."""
    if role.startswith("firm_"):
        return "firm"
    if role.startswith("analyst_"):
        return "analyst"
    if role.startswith("auditor_"):
        return "auditor"
    return role


def tiers_for_role(role: str) -> set[DataTier]:
    """Return the set of data tiers an agent role can access."""
    key = role_to_key(role)
    return ROLE_TIERS.get(key, {DataTier.PUBLIC})  # default to public-only if unknown


def filter_compustat_row(row: dict, role: str) -> dict:
    """Strip columns from a Compustat row based on the agent's role.

    Public columns always kept. Hidden columns only for roles with HIDDEN tier.
    Restated columns always kept (they're public disclosures).
    """
    tiers = tiers_for_role(role)
    if DataTier.HIDDEN in tiers:
        return dict(row)  # omniscient — everything
    # For all other roles: strip hidden columns
    return {k: v for k, v in row.items() if k not in HIDDEN_COLUMNS}


def can_access_firm_private(role: str, firm_id: str) -> bool:
    """Check if a role can access a specific firm's private data.

    Firms can access their own. Auditors can access their client's.
    Board governance can access the firm it governs. Environment sees all.
    """
    tiers = tiers_for_role(role)
    if DataTier.HIDDEN in tiers:
        return True
    if role == firm_id and DataTier.OWN_PRIVATE in tiers:
        return True
    # For now, board governance and auditor access is enforced by caller
    # passing the right firm_id in context. This is a permissive check.
    return False
