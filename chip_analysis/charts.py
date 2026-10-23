"""Inline SVG charts (no JS, no external libraries). Colors come from CSS variables in the report.

Palette: reference categorical slots 1-2 (validated light + dark with the dataviz validator).
Every mark carries a <title> tooltip; every chart is paired with a table in the report.
"""
import html

esc = lambda x: html.escape(str(x), quote=True)


def nice_max(v):
    """Smallest 'nice' axis maximum (1, 2, 2.5, 5 x 10^k) that is >= v."""
    if v <= 0:
        return 1
    candidates = [s * m for s in (1, 2, 2.5, 5) for m in (0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000, 100000)]
    return min(c for c in candidates if c >= v)


def hbar(rows, label_key, value_key, title, fmt=lambda v: f"{v}", width=640, series_var="--series-1", max_value=None):
    """Single-series horizontal bars from a zero baseline; value label at the tip."""
    left, bar_h, gap, top = 120, 18, 14, 8
    plot_w = width - left - 70
    height = top + len(rows) * (bar_h + gap) + 26
    vmax = max_value or nice_max(max([r[value_key] or 0 for r in rows] + [0]))
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">']
    for t in range(0, 5):
        x = left + plot_w * t / 4
        parts.append(f'<line x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{height - 22}" class="grid"/>'
                     f'<text x="{x:.1f}" y="{height - 6}" class="tick" text-anchor="middle">{esc(fmt(vmax * t / 4))}</text>')
    for i, r in enumerate(rows):
        y = top + i * (bar_h + gap)
        v = r[value_key] or 0
        w = max(plot_w * v / vmax, 0)
        parts.append(f'<text x="{left - 8}" y="{y + bar_h * 0.72:.1f}" class="label" text-anchor="end">{esc(r[label_key])}</text>')
        if w > 0:
            parts.append(f'<path d="{bar_path(left, y, w, bar_h)}" style="fill:var({series_var})"><title>{esc(r[label_key])}: {esc(fmt(v))}</title></path>')
        parts.append(f'<text x="{left + w + 6:.1f}" y="{y + bar_h * 0.72:.1f}" class="value">{esc(fmt(v))}</text>')
    parts.append(f'<line x1="{left}" y1="{top - 4}" x2="{left}" y2="{height - 22}" class="axis"/></svg>')
    return "".join(parts)


def bar_path(x, y, w, h, r=4):
    """Horizontal bar: square at the baseline (left), 4px rounded data end (right)."""
    r = min(r, w, h / 2)
    return (f"M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h - r:.1f} "
            f"Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z")


def grouped_hbar(groups, series, title, fmt, width=640):
    """groups: [(label, [v1, v2])]; series: [(name, css_var)]. Legend on top, labels at tips, 2px gap between bars."""
    left, bar_h, inner, gap, top = 150, 14, 2, 16, 30
    plot_w = width - left - 70
    n = len(series)
    height = top + len(groups) * (n * bar_h + (n - 1) * inner + gap) + 24
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">']
    lx = left
    for name, var in series:
        parts.append(f'<rect x="{lx}" y="6" width="12" height="12" rx="3" style="fill:var({var})"/><text x="{lx + 18}" y="16" class="label">{esc(name)}</text>')
        lx += 30 + 13 * len(name)
    for t in range(0, 5):
        x = left + plot_w * t / 4
        parts.append(f'<line x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{height - 20}" class="grid"/>'
                     f'<text x="{x:.1f}" y="{height - 6}" class="tick" text-anchor="middle">{esc(fmt(t / 4))}</text>')
    y = top
    for label, values in groups:
        block = n * bar_h + (n - 1) * inner
        parts.append(f'<text x="{left - 8}" y="{y + block / 2 + 4:.1f}" class="label" text-anchor="end">{esc(label)}</text>')
        for (name, var), v in zip(series, values):
            w = plot_w * (v or 0)
            parts.append(f'<path d="{bar_path(left, y, max(w, 0.5), bar_h)}" style="fill:var({var})"><title>{esc(label)} · {esc(name)}: {esc(fmt(v))}</title></path>'
                         f'<text x="{left + w + 6:.1f}" y="{y + bar_h - 3:.1f}" class="value">{esc(fmt(v))}</text>')
            y += bar_h + inner
        y += gap - inner
    parts.append(f'<line x1="{left}" y1="{top - 4}" x2="{left}" y2="{height - 20}" class="axis"/></svg>')
    return "".join(parts)


def histograms(panels, title, unit, bins=24, width=640):
    """Small multiples, shared x scale, one hue. panels: [(label, values, upper_limit)]."""
    allv = [v for _, vals, _ in panels for v in vals]
    lo, hi = min(allv), max(max(allv), max(u for _, _, u in panels if u is not None))
    span = (hi - lo) or 1
    edges = [lo + span * i / bins for i in range(bins + 1)]
    counts = []
    for _, vals, _ in panels:
        c = [0] * bins
        for v in vals:
            c[min(int((v - lo) / span * bins), bins - 1)] += 1
        counts.append(c)
    cmax = max(max(c) for c in counts) or 1
    left, panel_h, top, gapy = 150, 60, 6, 18
    plot_w = width - left - 20
    height = top + len(panels) * (panel_h + gapy) + 22
    bw = plot_w / bins
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">']
    for p, (label, vals, upper) in enumerate(panels):
        y0 = top + p * (panel_h + gapy) + panel_h
        parts.append(f'<text x="{left - 8}" y="{y0 - panel_h / 2 + 4:.1f}" class="label" text-anchor="end">{esc(label)}</text>'
                     f'<text x="{left - 8}" y="{y0 - panel_h / 2 + 18:.1f}" class="tick" text-anchor="end">n={len(vals)}</text>'
                     f'<line x1="{left}" y1="{y0}" x2="{left + plot_w}" y2="{y0}" class="axis"/>')
        for i, c in enumerate(counts[p]):
            if c:
                h = panel_h * c / cmax
                parts.append(f'<rect x="{left + i * bw + 1:.1f}" y="{y0 - h:.1f}" width="{bw - 2:.1f}" height="{h:.1f}" rx="1.5" style="fill:var(--series-1)">'
                             f'<title>{esc(label)}: {edges[i]:.2f}–{edges[i + 1]:.2f} {esc(unit)} · {c} 颗</title></rect>')
        if upper is not None:
            x = left + (upper - lo) / span * plot_w
            parts.append(f'<line x1="{x:.1f}" y1="{y0 - panel_h - 2}" x2="{x:.1f}" y2="{y0}" class="limit"><title>上限 {upper} {esc(unit)}</title></line>'
                         f'<text x="{x - 4 if x > left + plot_w - 60 else x + 4:.1f}" y="{y0 - panel_h + 8:.1f}" class="tick" '
                         f'text-anchor="{"end" if x > left + plot_w - 60 else "start"}">上限 {upper:g}</text>')
    for t in range(0, 5):
        v = lo + span * t / 4
        parts.append(f'<text x="{left + plot_w * t / 4:.1f}" y="{height - 6}" class="tick" text-anchor="middle">{v:.1f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def line(points, title, unit, width=640):
    """Single series over ordinal x (time buckets in order). points: [(x_label, y, tooltip)]."""
    left, top, plot_h, bottom = 56, 14, 180, 46
    plot_w = width - left - 20
    height = top + plot_h + bottom
    ys = [p[1] for p in points]
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.15 or 1
    lo, hi = lo - pad, hi + pad
    sx = lambda i: left + (plot_w * i / max(len(points) - 1, 1))
    sy = lambda v: top + plot_h - (v - lo) / (hi - lo) * plot_h
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">']
    for t in range(0, 5):
        v = lo + (hi - lo) * t / 4
        parts.append(f'<line x1="{left}" y1="{sy(v):.1f}" x2="{left + plot_w}" y2="{sy(v):.1f}" class="grid"/>'
                     f'<text x="{left - 6}" y="{sy(v) + 4:.1f}" class="tick" text-anchor="end">{v:.2f}</text>')
    # x labels look like "10-21T08:05"; the line breaks where the day changes (no fake continuity).
    day = lambda i: points[i][0][:5]
    segments, current = [], []
    for i, p in enumerate(points):
        if current and day(i) != day(i - 1):
            segments.append(current)
            current = []
        current.append(f"{'M' if not current else 'L'}{sx(i):.1f},{sy(p[1]):.1f}")
    segments.append(current)
    for seg in segments:
        parts.append(f'<path d="{" ".join(seg)}" class="series-line"/>')
    step = max(1, -(-len(points) // 6))
    for i, (x, y, tip) in enumerate(points):
        parts.append(f'<circle cx="{sx(i):.1f}" cy="{sy(y):.1f}" r="4" class="dot"><title>{esc(tip)}</title></circle>')
        new_day = i == 0 or day(i) != day(i - 1)
        if new_day:
            parts.append(f'<line x1="{sx(i):.1f}" y1="{top}" x2="{sx(i):.1f}" y2="{top + plot_h}" class="axis"/>'
                         f'<text x="{sx(i) + 4:.1f}" y="{top + 10}" class="label">{esc(x[:5])}</text>')
        if new_day or i % step == 0:
            parts.append(f'<text x="{sx(i):.1f}" y="{top + plot_h + 16}" class="tick" text-anchor="middle">{esc(x[6:])}</text>')
    parts.append(f'<text x="{left}" y="{height - 6}" class="tick">单位：{esc(unit)}；横轴为 5 分钟时段，竖线处换日，两天之间不连线</text></svg>')
    return "".join(parts)


CHART_CSS = """
.viz-root{--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--series-1:#2a78d6;--series-2:#eb6834;--critical:#d03b3b}
@media (prefers-color-scheme: dark){:root:where(:not([data-theme="light"])) .viz-root{--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--series-1:#3987e5;--series-2:#d95926;--critical:#d03b3b}}
:root[data-theme="dark"] .viz-root{--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--series-1:#3987e5;--series-2:#d95926;--critical:#d03b3b}
.chart{width:100%;height:auto;display:block;background:var(--surface-1);border-radius:10px}
.chart .grid{stroke:var(--grid);stroke-width:1}.chart .axis{stroke:var(--axis);stroke-width:1}
.chart .tick{fill:var(--muted);font:11px system-ui;font-variant-numeric:tabular-nums}.chart .label{fill:var(--text-secondary);font:12px system-ui}
.chart .value{fill:var(--text-primary);font:12px system-ui}.chart .limit{stroke:var(--critical);stroke-width:1.5}
.chart .series-line{fill:none;stroke:var(--series-1);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.chart .dot{fill:var(--series-1);stroke:var(--surface-1);stroke-width:2}
.chart path:hover,.chart rect:hover,.chart circle:hover{opacity:.8}
"""
