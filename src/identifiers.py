"""
Wave zeta: persistent identifier graph.

Entity types beyond the core (firm, CEO, facility, grant):
  - Director: board members with stable IDs; can hold seats at multiple
    firms (interlocking directorships).
  - Product: multiple products per firm, each with product_id and launch
    quarter.
  - Security: equity classes + bond issuances unified under security_id.

`build_crosswalk(state)` emits a single `crosswalk.csv` linking all
entity IDs for researchers (who-holds-what, who-sits-on-whose-board).

For this wave these are STORED but not yet extensively USED. The
infrastructure is in place for future enrichment (director independence
analysis, product-level revenue attribution, bond covenant studies).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Director:
    """Board director identity."""
    director_id: str                   # stable across quarters + firms
    name: str = ""
    age: int = 60
    seats: tuple = field(default_factory=tuple)  # tuple of firm_ids where currently seated
    independent: bool = True            # GAAP/NYSE definition of "independent"


@dataclass(frozen=True)
class Product:
    """A firm's product offering."""
    product_id: str
    firm_id: str
    name: str = ""
    generation: int = 1                 # G1..G4
    launch_quarter: int = 0
    discontinued_quarter: int | None = None


@dataclass(frozen=True)
class Security:
    """Equity class or debt instrument identity.

    For equities: one per firm's common-stock class (most firms have one).
    For debt: linked to DebtFacility via `linked_facility_id`.
    """
    security_id: str
    firm_id: str
    security_type: str                  # "common_equity" | "bond" | "convertible_bond" | "bank_term" | "revolver"
    linked_facility_id: str = ""        # when security_type != "common_equity"
    cusip: str = ""                     # from wrds_identifiers
    issue_quarter: int = 0


# ── Crosswalk builder ─────────────────────────────────────────────────

CROSSWALK_COLUMNS = [
    "run_id", "entity_type", "entity_id", "parent_firm_id",
    "name_or_descriptor", "detail1", "detail2", "detail3", "as_of_quarter",
]


def build_crosswalk(state) -> list[dict]:
    """Emit one row per entity for this run's crosswalk.csv.

    entity_type ∈ {"firm", "ceo", "director", "product", "security",
                   "facility", "grant"}
    """
    rows = []
    run_id = state.run_id

    # Firms (one row each)
    for fid, firm in state.firms.items():
        rows.append({
            "run_id": run_id,
            "entity_type": "firm",
            "entity_id": fid,
            "parent_firm_id": "",
            "name_or_descriptor": f"{firm.ceo_type or '?'} CEO",
            "detail1": f"incarnation={firm.incarnation}",
            "detail2": f"is_active={firm.is_active}",
            "detail3": f"auditor={firm.auditor_id}",
            "as_of_quarter": state.quarter,
        })

    # CEOs (one per incarnation, read from ceo_history)
    for fid, hist in getattr(state, "ceo_history", {}).items():
        for i, event in enumerate(hist):
            ceo_id = event.get("incoming_ceo_id", "") or event.get("departing_ceo_id", "")
            if not ceo_id:
                continue
            rows.append({
                "run_id": run_id,
                "entity_type": "ceo",
                "entity_id": f"{fid}_{ceo_id}_inc{i+1}",
                "parent_firm_id": fid,
                "name_or_descriptor": ceo_id,
                "detail1": f"tenure_q={event.get('departing_tenure_quarters', 0)}",
                "detail2": f"age={event.get('departing_age', 0)}",
                "detail3": event.get("event_type", ""),
                "as_of_quarter": event.get("event_quarter", 0),
            })

    # Directors (Wave theta): one row per director, with seats summarized.
    # `parent_firm_id` carries the first seat; `detail1` lists all seats
    # (interlocks visible in the dataset for network-analysis research).
    for did, director in getattr(state, "directors", {}).items():
        seats_list = list(director.seats)
        rows.append({
            "run_id": run_id,
            "entity_type": "director",
            "entity_id": did,
            "parent_firm_id": seats_list[0] if seats_list else "",
            "name_or_descriptor": director.name,
            "detail1": f"seats={','.join(seats_list)}",
            "detail2": f"age={director.age}",
            "detail3": f"independent={director.independent}",
            "as_of_quarter": state.quarter,
        })

    # Debt facilities
    for fid, firm in state.firms.items():
        for f in getattr(firm, "debt_facilities", ()):
            rows.append({
                "run_id": run_id,
                "entity_type": "facility",
                "entity_id": f.facility_id,
                "parent_firm_id": fid,
                "name_or_descriptor": f.facility_type,
                "detail1": f"principal={f.original_principal:.0f}",
                "detail2": f"coupon_q={f.coupon_rate_quarterly}",
                "detail3": f"status={f.status}",
                "as_of_quarter": f.origination_quarter,
            })
            # Also emit as a Security
            rows.append({
                "run_id": run_id,
                "entity_type": "security",
                "entity_id": f"SEC-{f.facility_id}",
                "parent_firm_id": fid,
                "name_or_descriptor": f.facility_type,
                "detail1": f"linked_facility={f.facility_id}",
                "detail2": f"maturity_q={f.maturity_quarter}",
                "detail3": f"amort={f.amortization_type}",
                "as_of_quarter": f.origination_quarter,
            })

    # Equity as a security (one common-stock class per firm)
    for fid, firm in state.firms.items():
        rows.append({
            "run_id": run_id,
            "entity_type": "security",
            "entity_id": f"EQ-{fid}",
            "parent_firm_id": fid,
            "name_or_descriptor": "common_equity",
            "detail1": f"shares={firm.shares_outstanding}",
            "detail2": f"price=${firm.equity_price:.2f}",
            "detail3": f"apic=${firm.apic/1e6:.1f}M",
            "as_of_quarter": state.quarter,
        })

    # Stock grants
    for fid, firm in state.firms.items():
        for g in getattr(firm, "ceo_stock_grants", ()):
            rows.append({
                "run_id": run_id,
                "entity_type": "grant",
                "entity_id": g.grant_id,
                "parent_firm_id": fid,
                "name_or_descriptor": g.grant_type,
                "detail1": f"shares={g.shares}",
                "detail2": f"strike={g.strike_price:.2f}",
                "detail3": f"ceo_incarnation={g.ceo_incarnation}",
                "as_of_quarter": g.grant_quarter,
            })

    # Product (one per firm, generation-based — minimal wire for Wave zeta)
    for fid, firm in state.firms.items():
        rows.append({
            "run_id": run_id,
            "entity_type": "product",
            "entity_id": f"PROD-{fid}-G{firm.product_generation}",
            "parent_firm_id": fid,
            "name_or_descriptor": f"SRT Gen{firm.product_generation}",
            "detail1": f"capability={firm.capability_stock:.1f}",
            "detail2": f"brand={firm.brand_stock:.1f}",
            "detail3": f"unit_cost={firm.base_unit_cost:.0f}",
            "as_of_quarter": state.quarter,
        })

    return rows
