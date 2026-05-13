"""
Restatement processing.

Pure accounting — no LLM calls. When triggered (by SEC, auditor, or
voluntary), reverses cumulative manipulation and produces dual-column
CompustatRow updates.

Triggers:
- "voluntary": firm self-corrects (reduces cumulative_manipulation to 0)
- "sec_forced": AAER enforcement action
- "auditor_forced": adverse audit opinion

The original CompustatRow values are preserved as-is. Restated values
go into the _restated columns. restatement_flag = 1 marks affected rows.
"""

from __future__ import annotations

from dataclasses import replace

from .types import CompustatRow, FirmState


def process_restatement(
    firm: FirmState,
    compustat_rows: list[CompustatRow],
    trigger: str,
    quarter: int,
) -> tuple[FirmState, list[CompustatRow], dict]:
    """Process a restatement for a firm.

    Reverses cumulative manipulation. Populates _restated columns on
    affected CompustatRows. Returns (updated_firm_state, updated_rows, event).

    Args:
        firm: current FirmState (has cumulative_manipulation > 0)
        compustat_rows: ALL CompustatRows for this run (modified in place)
        trigger: "voluntary" | "sec_forced" | "auditor_forced"
        quarter: current quarter (when restatement is announced)

    Returns:
        (new_firm_state, updated_compustat_rows, event_dict)
        event_dict is empty {} if no restatement occurred (e.g. nothing to reverse).
    """
    cumulative = firm.cumulative_manipulation
    if abs(cumulative) < 1.0:
        # Wave ν+9 Bug M5: a forced restatement of a clean firm should
        # still leave an audit trail. Previously this returned `{}` which
        # downstream code conflated with "no restatement attempted." Now
        # we return a structured no-op event so SEC-forced restatements
        # are visibly logged even when there is nothing to reverse.
        no_op_event = {
            "firm_id": firm.firm_id,
            "announcement_quarter": quarter,
            "trigger": trigger,
            "restated_start_quarter": quarter,
            "restated_end_quarter": quarter,
            "original_ni": 0.0,
            "restated_ni": 0.0,
            "restatement_amount": 0.0,
            "sec_flag": 1 if trigger == "sec_forced" else 0,
            "aaer_flag": 0,
            "outcome": "no_op",
            "note": (
                f"No material manipulation to reverse "
                f"(|cumulative|=${abs(cumulative):,.2f} < $1.00 threshold)."
            ),
        }
        return firm, compustat_rows, no_op_event

    # Track restated quarter range for the log
    restated_quarters: list[int] = []
    original_ni_sum = 0.0
    restated_ni_sum = 0.0

    # Find all rows for this firm that had non-zero manipulation
    updated_rows = []
    for row in compustat_rows:
        if row.firm_id != firm.firm_id:
            updated_rows.append(row)
            continue

        if abs(row.manipulation_amount) < 1.0:
            updated_rows.append(row)
            continue

        # This row had manipulation — compute restated values
        manip = row.manipulation_amount
        restated_ni = row.niq - manip  # remove manipulation from NI

        # Cascade: manipulation affects NI which affects RE which affects equity
        restated_re = row.req - manip
        restated_ceq = row.ceqq - manip
        restated_at = row.atq - manip  # overstated assets shrink

        updated_row = CompustatRow(**row.as_dict())
        updated_row.niq_restated = restated_ni
        updated_row.req_restated = restated_re
        updated_row.ceqq_restated = restated_ceq
        updated_row.atq_restated = restated_at
        updated_row.restatement_flag = 1
        updated_row.restatement_quarter = quarter
        updated_rows.append(updated_row)

        # Track for event log. Wave ν+9 Bug L2: convert 1-indexed fqtr
        # (Q1..Q4) to 0-indexed absolute-quarter index that matches the
        # `firm.quarter` convention used by the rest of the codebase.
        # Restated_quarters previously used a 1-indexed value, so any
        # caller comparing it to firm.quarter was off by one.
        abs_q = (row.fyearq - 2031) * 4 + (row.fqtr - 1)
        restated_quarters.append(abs_q)
        original_ni_sum += row.niq
        restated_ni_sum += restated_ni

    # Reset firm's cumulative manipulation to zero
    new_firm = firm.evolve(
        cumulative_manipulation=0.0,
        manipulation_this_quarter=0.0,
    )

    # Build restatement event
    event = {
        "firm_id": firm.firm_id,
        "announcement_quarter": quarter,
        "trigger": trigger,
        "restated_start_quarter": min(restated_quarters) if restated_quarters else quarter,
        "restated_end_quarter": max(restated_quarters) if restated_quarters else quarter,
        "original_ni": original_ni_sum,
        "restated_ni": restated_ni_sum,
        "restatement_amount": original_ni_sum - restated_ni_sum,
        "sec_flag": 1 if trigger == "sec_forced" else 0,
        "aaer_flag": 1 if trigger == "sec_forced" else 0,
    }
    return new_firm, updated_rows, event
