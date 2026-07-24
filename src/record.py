"""Decision record writer — writes decision_record.md to disk.

Per SPEC: every number traced to a source sentence. The decision record is the
audit trail. Write it with pathlib, not stdout. Open it on stage.

The record includes:
  - Block config (what field, what crop, how many picks left)
  - Every price source with its AMS slug, district, price, published date, age
  - The binding wage floor, all candidates, and why it bound
  - The full cost floor arithmetic, line by line
  - The net per flat and the band
  - Every placeholder explicitly marked
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .decision import Band, DecisionResult, InputTrace
from .wages import WageFloorResult


def _fmt_money(val: float | None) -> str:
    """Format a value as USD, or mark as N/A."""
    if val is None:
        return "N/A"
    return f"${val:.2f}"


def _fmt_money_range(low: float | None, high: float | None) -> str:
    """Format a price range."""
    if low is None and high is None:
        return "not quoted"
    if low == high:
        return _fmt_money(low)
    return f"{_fmt_money(low)} – {_fmt_money(high)}"


def _is_placeholder(val) -> bool:
    """Check if a grower cost value is a placeholder (None)."""
    return val is None


def _cost_status(val, all_placeholder: bool) -> str:
    """Build the status column text for a grower cost input.

    - None values are always placeholders (no value provided).
    - If costs_are_placeholders is True, non-None values are demo placeholders too.
    - Otherwise, the value is marked as real grower input.
    """
    if _is_placeholder(val):
        return "⚠️ PLACEHOLDER — no value provided"
    if all_placeholder:
        return "⚠️ PLACEHOLDER — demo value, not from grower"
    return "Real (grower input)"


def _arith_source(val, label: str, all_placeholder: bool, pct: bool = False) -> str:
    """Build the source column text for the cost floor arithmetic table."""
    if _is_placeholder(val):
        unit = "0%" if pct else "$0.00"
        return f"⚠️ PLACEHOLDER — {label} not provided, treated as {unit}"
    if all_placeholder:
        return f"⚠️ PLACEHOLDER — demo {label}, not from grower"
    return f"Grower input: {label}"


def write_decision_record(
    result: DecisionResult,
    output_path: Path | str = "decision_record.md",
) -> Path:
    """Write the decision record as a Markdown file.

    Args:
        result:       The DecisionResult from decide().
        output_path:  Where to write the file. Defaults to decision_record.md
                      in the current directory.

    Returns:
        The Path object for the written file.
    """
    output_path = Path(output_path)
    trace = result.input_trace
    cost = result.cost_floor
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = []
    lines.append("# Harvest Decision Record")
    lines.append("")
    lines.append(f"_Generated: {now}_")
    lines.append("")

    # --- Band ---
    lines.append("## Decision: " + result.band.value)
    lines.append("")
    lines.append(f"**{result.band_reason}**")
    lines.append("")
    if result.confidence_gated:
        lines.append("> ⚠️ **Confidence gate fired.** The agent stayed silent.")
        lines.append(f"> {result.confidence_reason}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # --- Block config ---
    bc = trace.block_config
    lines.append("## Block Configuration")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Grower ID | {bc.get('grower_id', 'N/A')} |")
    lines.append(f"| Region | {bc.get('region', 'N/A')} |")
    lines.append(f"| Crop | {bc.get('crop', 'N/A')} |")
    lines.append(f"| Acres standing | {bc.get('acres_standing', 'N/A')} |")
    lines.append(f"| Picks remaining | {bc.get('picks_remaining', 'N/A')} |")
    lines.append(f"| Pick interval | {bc.get('pick_interval', 'N/A')} |")
    lines.append(f"| Unit | {bc.get('unit', 'N/A')} |")
    lines.append("")

    # --- Price sources ---
    lines.append("## Market Price Inputs")
    lines.append("")
    lines.append(f"Independent sources: **{trace.independent_source_count}**")
    lines.append("")
    if trace.price_sources:
        lines.append("| Source | Slug | District | Organic | Price range | Mostly | Published | Age (hrs) | Report comment |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for src in trace.price_sources:
            organic = "Yes" if src.organic else "No"
            price_range = _fmt_money_range(src.low_price, src.high_price)
            mostly = _fmt_money_range(src.mostly_low, src.mostly_high)
            rep_cmt = (src.rep_cmt or "").replace("|", "\\|")
            lines.append(
                f"| {src.report_title} | {src.slug_name} ({src.slug_id}) | "
                f"{src.district} | {organic} | {price_range} | {mostly} | "
                f"{src.published_date} | {src.data_age_hours:.1f} | {rep_cmt} |"
            )
        lines.append("")
        lines.append("> Every price above comes from a live USDA AMS MARS API call.")
        lines.append("> The `source_row` dict in the program preserves the raw JSON for provenance.")
        lines.append("")
    else:
        lines.append("_No price sources available._")
        lines.append("")

    # --- Wage floors ---
    wf = trace.wage_floors
    lines.append("## Wage Floor Selection")
    lines.append("")
    lines.append(f"**Binding rate: {_fmt_money(wf.get('binding_rate'))}/hr — {wf.get('binding_label', 'N/A')}**")
    lines.append("")
    lines.append(f"{wf.get('reason', 'N/A')}")
    lines.append("")
    lines.append("| Candidate | Rate | Applies to | Binding? | Source |")
    lines.append("|---|---|---|---|---|")
    for c in wf.get("candidates", []):
        binding = "✅ **Yes**" if c.get("binding") else "No"
        lines.append(
            f"| {c['label']} | {_fmt_money(c['rate'])}/hr | "
            f"{c['applies_to']} | {binding} | {c['source']} |"
        )
    lines.append("")

    # --- Grower costs ---
    gc = trace.grower_costs
    all_placeholder = gc.get("costs_are_placeholders", False)

    lines.append("## Grower-Side Costs")
    lines.append("")
    lines.append("| Input | Value | Status |")
    lines.append("|---|---|---|")
    fph = gc.get("flats_per_person_hour")
    lines.append(f"| Flats per person-hour (pick rate) | {fph if fph is not None else '—'} | {_cost_status(fph, all_placeholder)} |")
    cp = gc.get("cooling_pack_per_flat")
    lines.append(f"| Cooling & packing per flat | {_fmt_money(cp) if cp is not None else '—'} | {_cost_status(cp, all_placeholder)} |")
    comm = gc.get("commission_pct")
    lines.append(f"| Commission % | {comm if comm is not None else '—'}% | {_cost_status(comm, all_placeholder)} |")
    fr = gc.get("freight_per_flat")
    lines.append(f"| Freight per flat | {_fmt_money(fr) if fr is not None else '—'} | {_cost_status(fr, all_placeholder)} |")
    ext = gc.get("external_signals_triggered")
    lines.append(f"| External signals triggered | {ext} | {'⚠️ Placeholder (no Octen call in this run)' if not ext else 'Yes'} |")
    lines.append("")

    # --- Cost floor arithmetic ---
    lines.append("## Cost Floor Arithmetic")
    lines.append("")
    lines.append("Per SPEC section 4:")
    lines.append("")
    lines.append("```")
    lines.append("  net = expected_price - harvest_labour - cooling_pack - commission - freight")
    lines.append("  harvest_labour_per_flat = binding_wage / flats_per_person_hour")
    lines.append("```")
    lines.append("")
    lines.append("| Component | Value | Source |")
    lines.append("|---|---|---|")
    lines.append(f"| Expected price (per flat) | {_fmt_money(result.expected_price)} | AMS MARS (see price sources above) |")
    lines.append(f"| Binding wage | {_fmt_money(cost.binding_wage)}/hr | {cost.binding_label} |")
    fph_val = gc.get("flats_per_person_hour")
    if _is_placeholder(fph_val):
        lines.append("| Flats per person-hour | ⚠️ PLACEHOLDER | Grower input |")
    else:
        lines.append(f"| Flats per person-hour | {fph_val} | {_arith_source(fph_val, 'pick rate', all_placeholder)} |")
    lines.append(f"| → Harvest labour per flat | {_fmt_money(cost.harvest_labour_per_flat)} | binding_wage / flats_per_hr |")
    lines.append(f"| Cooling & packing per flat | {_fmt_money(cost.cooling_pack_per_flat)} | {_arith_source(gc.get('cooling_pack_per_flat'), 'cooling/packing', all_placeholder)} |")
    lines.append(f"| Commission per flat | {_fmt_money(cost.commission_per_flat)} | {_arith_source(gc.get('commission_pct'), 'commission', all_placeholder, pct=True)} |")
    lines.append(f"| Freight per flat | {_fmt_money(cost.freight_per_flat)} | {_arith_source(gc.get('freight_per_flat'), 'freight', all_placeholder)} |")
    lines.append(f"| **Total cost per flat** | **{_fmt_money(cost.total_cost_per_flat)}** | sum of above |")
    lines.append(f"| **Net per flat** | **{_fmt_money(result.net_per_flat)}** | price − total cost |")
    lines.append("")

    if cost.crew_blended:
        lines.append(f"**Crew blend:** {_fmt_money(cost.blended_labour_per_flat)}")
        lines.append("")

    # --- Notes ---
    if cost.notes:
        lines.append("### Notes")
        lines.append("")
        for note in cost.notes:
            lines.append(f"- {note}")
        lines.append("")

    # --- Band explanation ---
    lines.append("## Band Determination")
    lines.append("")
    lines.append("| Band | Condition | Action |")
    lines.append("|---|---|---|")
    lines.append("| GO | net positive | Pick as planned, no alert |")
    lines.append("| PARTIAL | net near zero AND external signal | First-grade-only pick, shorten crew, reassess |")
    lines.append("| ABANDON | net below zero by more than labour term | Skip pick, trigger recovery routing |")
    lines.append("| SILENT | confidence gate fired | No action, record why |")
    lines.append("")
    lines.append(f"**Result: {result.band.value}**")
    lines.append("")
    lines.append(f"{result.band_reason}")
    lines.append("")

    # --- Summary ---
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"```\n{result.summary}\n```")
    lines.append("")

    # --- Honesty footer ---
    lines.append("---")
    lines.append("")
    lines.append("## Honesty Notes")
    lines.append("")
    lines.append("- Market prices are **real**, from live USDA AMS MARS API calls.")
    if all_placeholder:
        lines.append("- Grower-side costs (pick rate, cooling, commission, freight) are **placeholders** — demo values, not from a real grower.")
    else:
        lines.append("- Grower-side costs marked Real are from grower input; marked ⚠️ are placeholders.")
    lines.append("- Wage floor figures are from the DOL IFR (Oct 2025) and CA DIR. Verify before quoting on stage.")
    lines.append("- This is not a backtest. The claim is that the decision is currently made blind and this makes it legible.")
    lines.append("")

    # --- Write to disk ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
