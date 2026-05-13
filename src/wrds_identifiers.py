"""
WRDS-style firm identifiers.

Real WRDS uses gvkey (primary key), tic (ticker), cusip, conm (company name),
and sic (industry code). We skip gvkey (firm_id serves the same role in our
panel) but DO provide:

- datadate: fiscal quarter-end date (YYYY-MM-DD) — critical for any time-series
- tic:      ticker symbol (synthetic but stable per firm index)
- conm:     company name (from src/personalities.py)
- sic:      industry code (constant for the simulation's industry template)
- cusip:    9-char synthetic CUSIP (enables downstream CRSP/TRACE-style linking)

Usage:
    from src.wrds_identifiers import datadate_for, identifiers_for_firm

    # For a single Compustat row
    dd = datadate_for(row.fyearq, row.fqtr)  # "2031-03-31"
    ids = identifiers_for_firm(row.firm_id)
    # ids = {"tic": "AETR", "conm": "Aeterna Therapeutics", "sic": "2836"}
"""

from __future__ import annotations

from .personalities import get_company_name


# Senolytic regenerative therapy — pharmaceutical preparations (SIC 2836 = biologics)
DEFAULT_SIC = "2836"


# Ticker map: maps firm index -> ticker.
# Keep synthetic but deterministic per firm_{idx}; extend as personalities grow.
_TICKER_BY_IDX = {
    0: "AETR",  # Aeterna Therapeutics
    1: "GENV",  # GenVita Sciences
    2: "NOVA",  # NovaLife Therapeutics
    3: "BIOA",  # BioAge Pharma
    4: "SENO",  # Senova Bio
    5: "MERI",  # Meridian Longevity
    6: "CHRO",  # Chronos Therapeutics
    7: "APEX",  # Apex Regenerative
}


# Map (fqtr) -> last day of fiscal quarter (assuming calendar-year fiscal)
# Q1 ends March 31, Q2 June 30, Q3 September 30, Q4 December 31
_QTR_END_MMDD = {
    1: ("03", "31"),
    2: ("06", "30"),
    3: ("09", "30"),
    4: ("12", "31"),
}


def datadate_for(fyearq: int, fqtr: int) -> str:
    """Return ISO date for the end of the fiscal quarter."""
    mm, dd = _QTR_END_MMDD.get(fqtr, ("12", "31"))
    return f"{fyearq}-{mm}-{dd}"


def anndate_for(fyearq: int, fqtr: int) -> str:
    """Return ISO date for the typical announcement date of this fiscal
    quarter's earnings (30 days after quarter-end)."""
    mm, dd = _QTR_END_MMDD.get(fqtr, ("12", "31"))
    # Add ~30 days: simplistic but stable. Map quarter-end + 30 days.
    month = int(mm) + 1
    year = fyearq
    if month > 12:
        month -= 12
        year += 1
    return f"{year}-{month:02d}-{dd}"


def ticker_for(firm_id: str) -> str:
    """Return the ticker for a firm_id like 'firm_0'."""
    try:
        idx = int(firm_id.split("_")[-1])
    except (ValueError, IndexError):
        return firm_id.upper()[:4]
    return _TICKER_BY_IDX.get(idx, f"F{idx:03d}")


def cusip_for(firm_id: str) -> str:
    """Return a synthetic 9-char CUSIP for a firm_id.

    Real CUSIPs have 6-char issuer + 2-char issue + 1-char checksum. We
    generate a stable, syntactically-valid-looking string per firm index.
    Not registered with the CUSIP Global Services — purely for research
    database linking in downstream sim workflows.
    """
    try:
        idx = int(firm_id.split("_")[-1])
    except (ValueError, IndexError):
        idx = 0
    # Use ticker + deterministic suffix + checksum-ish digit
    tic = ticker_for(firm_id).ljust(4, "X")[:4]
    issuer = (tic + f"{idx:02d}")[:6].upper()
    issue = "10"   # common equity (standard convention)
    checksum = str((sum(ord(c) for c in issuer + issue)) % 10)
    return issuer + issue + checksum


def identifiers_for_firm(firm_id: str) -> dict:
    """Return a dict of {tic, conm, sic, cusip} for a firm_id."""
    try:
        idx = int(firm_id.split("_")[-1])
    except (ValueError, IndexError):
        idx = 0
    return {
        "tic": ticker_for(firm_id),
        "conm": get_company_name(idx),
        "sic": DEFAULT_SIC,
        "cusip": cusip_for(firm_id),
    }


def abs_quarter_to_fy_fq(q: int) -> tuple[int, int]:
    """Map absolute quarter number (1-based) to (fyearq, fqtr)."""
    return (2031 + (q - 1) // 4, ((q - 1) % 4) + 1)


def abs_quarter_to_datadate(q: int) -> str:
    """Map absolute quarter number (1-based) to datadate string."""
    fy, fq = abs_quarter_to_fy_fq(q)
    return datadate_for(fy, fq)
