"""The network spine: 50 clinics drawn as vertebrae. Clinics with revenue at stake shift out of
line in proportion to the dollars at stake, so the problems are visible before any number is read."""
from __future__ import annotations

import html
import math

from style import INK, RASPBERRY, SLATE, TEAL

WIDTH, HEIGHT, AXIS_Y = 1000, 230, 168
MAX_SHIFT = 105
FLAG_ABOVE = 150_000  # dollars at stake before a clinic counts as out of alignment


def _money(x: float) -> str:
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}K"


def spine_svg(clinics: list[dict]) -> str:
    """clinics: dicts with location_id, city, total_revenue_at_stake, largest_lever."""
    clinics = sorted(clinics, key=lambda c: c["location_id"])
    n = len(clinics)
    pitch = (WIDTH - 40) / n
    body_w, body_h = pitch * 0.62, 30
    top = max((c["total_revenue_at_stake"] or 0) for c in clinics) or 1
    parts = [f'<line x1="14" y1="{AXIS_Y}" x2="{WIDTH - 14}" y2="{AXIS_Y}" stroke="{SLATE}" '
             f'stroke-width="1" stroke-dasharray="2 4" />']
    labels = []
    flagged_x = [20 + i * pitch for i, c in enumerate(clinics) if (c["total_revenue_at_stake"] or 0) >= FLAG_ABOVE]
    for i, c in enumerate(clinics):
        stake = c["total_revenue_at_stake"] or 0
        flagged = stake >= FLAG_ABOVE
        shift = MAX_SHIFT * math.sqrt(stake / top) if flagged else 0
        x = 20 + i * pitch + (pitch - body_w) / 2
        y = AXIS_Y - body_h / 2 - shift
        color = RASPBERRY if flagged else TEAL
        tip = html.escape(f"{c['location_id']} {c['city']}: {_money(stake)} a year at stake"
                          + (f" ({c['largest_lever']})" if flagged else ""))
        if i:  # intervertebral disc
            parts.append(f'<rect x="{x - (pitch - body_w) / 2 - 2:.1f}" y="{AXIS_Y - 9}" width="'
                         f'{pitch - body_w + 4:.1f}" height="18" rx="4" fill="#C9D6D3" />')
        if flagged:
            parts.append(f'<line x1="{x + body_w / 2:.1f}" y1="{AXIS_Y}" x2="{x + body_w / 2:.1f}" '
                         f'y2="{y + body_h:.1f}" stroke="{RASPBERRY}" stroke-width="1.5" />')
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{body_w:.1f}" height="{body_h}" rx="5" '
                     f'fill="{color}"><title>{tip}</title></rect>')
        if flagged:
            # Extend the label leftward when another flagged clinic sits close on the right.
            crowded = any(0 < fx - (20 + i * pitch) < 170 for fx in flagged_x)
            anchor = "end" if crowded or i > n * 0.8 else "start"
            lx = x + body_w if anchor == "end" else x
            labels.append(
                f'<text x="{lx:.1f}" y="{y - 22:.1f}" text-anchor="{anchor}" font-size="15" '
                f'font-weight="600" fill="{INK}">{html.escape(c["location_id"])} {html.escape(c["city"])}</text>'
                f'<text x="{lx:.1f}" y="{y - 6:.1f}" text-anchor="{anchor}" font-size="13" '
                f'fill="{SLATE}">{_money(stake)} a year, {html.escape(c["largest_lever"])}</text>')
    return (f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" width="100%" role="img" '
            f'aria-label="Clinic network spine: {sum(1 for c in clinics if (c["total_revenue_at_stake"] or 0) >= FLAG_ABOVE)} '
            f'clinics out of alignment" style="font-family: Familjen Grotesk, sans-serif; overflow: visible">'
            + "".join(parts) + "".join(labels) + "</svg>")
