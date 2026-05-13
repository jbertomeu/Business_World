"""
Investor voice (Wave ν+12).

A short market-analyst commentary delivered to each active firm at the
start of every quarter, just before the firm makes its operating +
financing decision. The voice reads PUBLIC quarterly data (own
Compustat + peer panel + macro) and produces a 2-3 sentence note on
what the market would view as positive next-quarter moves and what is
of concern.

INFORMATION BOUNDARY: voice sees ONLY public information — no private
firm state, no world secrets, no manipulation truth. It is the
external investor / equity analyst perspective, not the CFO's.

Purpose: introduces a market-side feedback loop that exists in reality
but was previously absent in the simulation. Cash-hoarding firms hear
"the market notices this cash position and would welcome a credible
deployment plan"; weak firms hear "the runway is closing and equity
markets are sceptical". Firms can ignore the voice; or act on it.
Behaviour is emergent — no thresholds, no numbers, no forcing.

Output: appended to `state.investor_notes_by_firm` (dict[firm_id, str])
which the firm decision prompt renders next quarter.
"""

from __future__ import annotations

from .types import FirmState, MacroState
from .llm_backends import LLMBackend


INVESTOR_VOICE_SYSTEM_PROMPT = """You are a senior equity-research analyst at a major bank writing a
short market note on a specific public biotech firm. You speak for the
broader investor base — pension funds, mutual funds, hedge funds —
who own the firm's stock and watch its capital-allocation choices
each quarter.

Your audience is the firm's CEO/CFO. Your job: tell them, candidly,
what the public market would view as positive operating and financing
moves NEXT quarter given the firm's current position and the industry
context, and what is of concern.

Examples of moves the market typically views positively (when the
situation warrants):
  - A clear capital-return programme (buybacks, dividends) when cash
    has piled up well beyond credible operating need and no specific
    deployment opportunity has been articulated.
  - A credible M&A move when the firm sits on extreme cash, sub-scale
    peers exist in the industry, and a combination would create real
    scale or fill a strategic gap.
  - Disciplined R&D investment when runway is comfortable and the
    generational path is credible.
  - Operational restructuring (lower SGA, narrower focus, exit a
    non-core programme) when burn is high without commensurate
    progress.
  - Equity raising when growth requires capital, share price is fair
    or strong, and dilution is manageable.

Examples of concerns the market typically raises:
  - Persistent unproductive cash hoarding signals weak governance —
    over many quarters investors increasingly mark down the multiple
    they apply to "trapped" cash.
  - Repeated equity raises at falling prices look like a death spiral
    and erode the firm's ability to raise on reasonable terms.
  - Sustained negative cash from operations with no convergence path
    pushes the firm toward credit rating downgrade, covenant pressure,
    activist intervention, or eventual takeover.
  - Persistent under-performance relative to peers in a maturing
    industry invites consolidation pressure — the firm becomes a
    plausible target.

GROUND RULES for your note:
  - 2-3 sentences. Terse. No bullet points.
  - You may suggest direction but do not prescribe numbers — speak the
    language of equity research, not budgeting. "Consider returning
    more capital" not "buy back $200M of stock".
  - Be honest about both positives and concerns; do not pile on or
    sugar-coat. This is a market view, not a board memo.
  - Refer to the firm in the second person ("you should consider...").

Output JSON:
```json
{"note": "<2-3 sentence candid market note>"}
```

Output ONLY the JSON wrapped in ```json ... ```."""


def build_investor_voice_prompt(
    firm: FirmState,
    public_competitors: dict[str, dict],
    macro: MacroState,
    own_public_panel: list[dict] | None = None,
    industry_character_str: str = "",
) -> tuple[str, str]:
    """Build (system, user) prompt for the investor voice.

    Only PUBLIC information is included. The user prompt mirrors the
    public-Compustat slice the sell-side analyst sees, plus the firm's
    own publicly-observable trajectory and the peer panel.
    """
    system = INVESTOR_VOICE_SYSTEM_PROMPT

    # Own firm's recent public trajectory (last 4-6 quarters)
    own_lines = []
    for row in (own_public_panel or [])[-6:]:
        own_lines.append(
            f"  Q{row.get('fyearq','?')}Q{row.get('fqtr','?')}: "
            f"rev=${(row.get('saleq',0) or 0)/1e6:.1f}M  "
            f"ni=${(row.get('niq',0) or 0)/1e6:.1f}M  "
            f"cash=${(row.get('cheq',0) or 0)/1e6:.1f}M  "
            f"ltd=${(row.get('dlttq',0) or 0)/1e6:.1f}M  "
            f"price=${(row.get('prccq',0) or 0):.2f}"
        )

    # Peer panel — public competitors, snapshot only
    peer_lines = []
    for cid, cinfo in sorted(public_competitors.items()):
        if cid == firm.firm_id:
            continue
        rev = cinfo.get("revenue", 0) or 0
        share = cinfo.get("market_share", 0) or 0
        gen = cinfo.get("generation", 1)
        ep = cinfo.get("equity_price", 0) or 0
        peer_lines.append(
            f"  {cid}: rev=${rev/1e6:.1f}M  share={share:.1%}  gen={gen}  px=${ep:.2f}"
        )

    user = f"""=== Q{macro.fqtr} {macro.fyear} — Market note on {firm.firm_id} ===

{industry_character_str or '(industry context unavailable)'}

THE FIRM (publicly observable):
  shares outstanding: {firm.shares_outstanding:,}
  recent equity price: ${firm.equity_price:.2f}
  recent EPS guidance 1Q / 1Y: ${firm.last_eps_guidance_1q:.2f} / ${firm.last_eps_guidance_1y:.2f}

OWN RECENT QUARTERS (public Compustat):
{chr(10).join(own_lines) if own_lines else '  (no history yet)'}

PEERS THIS QUARTER (public):
{chr(10).join(peer_lines) if peer_lines else '  (no peers visible)'}

MACRO: Risk-free {macro.risk_free_rate:.1%}/Q

Write the market note."""

    return system, user


def make_investor_voice(backend: LLMBackend, state_ref: list):
    """Factory: create the investor-voice agent.

    Returns a callable
        voice_fn(firm, public_competitors, macro, own_public_panel,
                 industry_character_str) -> str
    that returns a 2-3 sentence market note for the firm. Empty string
    on LLM failure (so the simulation never blocks on it).
    """

    def voice_fn(
        firm: FirmState,
        public_competitors: dict[str, dict],
        macro: MacroState,
        own_public_panel: list[dict] | None = None,
        industry_character_str: str = "",
    ) -> str:
        try:
            system, user = build_investor_voice_prompt(
                firm, public_competitors, macro,
                own_public_panel, industry_character_str,
            )
            result = backend.complete_json(system, user)
            if result is None:
                return ""
            return str(result.get("note", ""))[:1200]
        except Exception:
            return ""

    return voice_fn
