"""Plot pilot sweep results: globs sweep_results_*.json, averages across trials.

Writes sweep_tokens.png, sweep_cost.png, sweep_latency.png and a self-contained
sweep_report.html (table + plots inlined as base64) next to this file.
"""

import base64
import glob
import io
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = Path(__file__).resolve().parent
COLORS = {  # categorical slots 1-3 (validated all-pairs)
    "claude-haiku-4-5": "#2a78d6",
    "claude-sonnet-4-6": "#eb6834",
    "claude-opus-4-7": "#1baf7a",
}
SHORT = {"claude-haiku-4-5": "Haiku 4.5", "claude-sonnet-4-6": "Sonnet 4.6",
         "claude-opus-4-7": "Opus 4.7"}
MARKER = {"off": "o", "on": "D"}
EFFORT_SIZE = {None: 10, "low": 8, "medium": 11, "high": 15}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
EXCLUDED: set[str] = set()


def load():
    """Return one aggregated row per cell, averaged across trial files."""
    by_cell = defaultdict(list)
    meta = {}
    for f in sorted(glob.glob(str(HERE / "sweep_results_*.json"))):
        for c in json.loads(Path(f).read_text()):
            key = (c["model"], c["thinking"], c["effort"])
            meta[key] = c
            by_cell[key].append(c["sims"])
    rows = []
    for key, trials in by_cell.items():
        # Unscored sims (harness/judge errors) carry no reward and no messages;
        # drop them rather than count them as failures or $0 tasks.
        sims = [s for t in trials for s in t
                if s["termination_reason"] != "infrastructure_error"]
        scored = {s["task_id"] for s in sims}
        EXCLUDED.update(s["task_id"] for t in trials for s in t
                        if s["termination_reason"] == "infrastructure_error"
                        and s["task_id"] not in scored)
        n = len(sims)
        if not n:
            continue
        passes = sum(s["passed"] for s in sims)
        cost = sum(s["agent_cost"] for s in sims)
        secs = sum(s["agent_generation_seconds"] for s in sims)
        rows.append({
            "model": key[0], "thinking": key[1], "effort": key[2],
            "n": n, "passes": passes, "pass_rate": 100 * passes / n,
            "out_tok": sum(s["output_tokens"] for s in sims) / n,
            "in_tok": sum(s["input_tokens"] for s in sims) / n,
            "cost": cost / n,
            "user_cost": sum(s["user_cost"] for s in sims) / n,
            "secs": secs / n,
            "p50": statistics.median(s["agent_generation_seconds"] for s in sims),
            "cost_per_success": cost / passes if passes else math.inf,
            "secs_per_success": secs / passes if passes else math.inf,
            "turns": sum(s["agent_turns"] for s in sims) / n,
            "complete": meta[key]["complete"],
        })
    order = list(COLORS)
    rows.sort(key=lambda r: (order.index(r["model"]), r["thinking"]))
    return rows


def figure(rows, xkey, xlabel, fname):
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    for model, color in COLORS.items():
        pts = [r for r in rows if r["model"] == model]
        pts.sort(key=lambda r: r["thinking"] == "on")
        if len(pts) == 2:  # thin connector: thinking off -> on for this model
            ax.plot([p[xkey] for p in pts], [p["pass_rate"] for p in pts],
                    ":", color=color, lw=1.5, alpha=0.7, zorder=1)
        for p in pts:
            ax.plot([p[xkey]], [p["pass_rate"]], MARKER[p["thinking"]],
                    color=color, markersize=EFFORT_SIZE[p["effort"]],
                    markeredgecolor="#fcfcfb", markeredgewidth=2, zorder=3)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel("Pass rate (%)", color=MUTED)
    ax.set_ylim(-8, 108)
    ax.set_yticks(range(0, 101, 20))
    ax.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED)
    if xkey == "cost":
        ax.xaxis.set_major_formatter(lambda v, _: f"${v:.2f}")
    series = []
    for model, color in COLORS.items():
        for r in rows:
            if r["model"] == model:
                eff = f" · {r['effort']}" if r["effort"] else ""
                series.append(Line2D([], [], marker=MARKER[r["thinking"]], ls="",
                                     color=color, markersize=8,
                                     label=f"{SHORT[model]} · thinking {r['thinking']}{eff}"))
    leg1 = ax.legend(handles=series, loc="upper left", bbox_to_anchor=(1.01, 1),
                     frameon=False, title="◆ = thinking on", alignment="left", fontsize=8,
                     title_fontsize=8, labelcolor=INK)
    ax.add_artist(leg1)
    sizes = [Line2D([], [], marker="o", ls="", color="#9a9893",
                    markersize=EFFORT_SIZE[e], label=lab)
             for e, lab in [("low", "effort low"), ("high", "effort high"),
                            (None, "no effort param")]]
    ax.legend(handles=sizes, loc="lower left", bbox_to_anchor=(1.01, 0),
              frameon=False, fontsize=8, labelcolor=MUTED, labelspacing=1.2)
    n = max((r["n"] for r in rows), default=0)
    ax.set_title(f"tau2 airline pilot · n={n} tasks/cell",
                 fontsize=10, color=INK, loc="left")
    fig.subplots_adjust(left=0.08, right=0.70, top=0.92, bottom=0.12)
    fig.savefig(HERE / fname, facecolor=fig.get_facecolor())
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def fmt_money(v):
    return "∞" if math.isinf(v) else f"${v:.3f}"


def fmt_s(v):
    return "∞" if math.isinf(v) else f"{v:.1f}s"


def report(rows, imgs, rec):
    trs = "\n".join(
        f"<tr><td><span class=dot style='background:{COLORS[r['model']]}'></span>"
        f"{SHORT[r['model']]}</td><td>{r['thinking']}</td><td>{r['effort'] or '—'}</td>"
        f"<td>{r['passes']}/{r['n']}</td><td>{r['pass_rate']:.0f}%</td>"
        f"<td>${r['cost']:.3f}</td><td>{fmt_money(r['cost_per_success'])}</td>"
        f"<td>{r['out_tok']:.0f}</td><td>{r['in_tok']/1000:.1f}k</td>"
        f"<td>{r['turns']:.1f}</td><td>{r['secs']:.1f}s</td><td>{r['p50']:.1f}s</td>"
        f"<td>{fmt_s(r['secs_per_success'])}</td><td>${r['user_cost']:.3f}</td></tr>"
        for r in rows)
    n = max((r["n"] for r in rows), default=0)
    excl_note = (
        f"n={n} scored tasks per cell; task(s) {', '.join(sorted(EXCLUDED))} excluded "
        "because the communicate_info LLM judge defaults to an OpenAI model and no "
        "OpenAI key was available, so those runs were never scored. "
        if EXCLUDED else
        f"n={n} tasks per cell; task 11 was re-run with the substring "
        "communicate_info scorer because the default LLM judge needs an OpenAI key "
        "(the other four tasks have no communicate_info check), ")
    total = sum(s["agent_cost"] + s["user_cost"]
                for f in glob.glob(str(HERE / "sweep_results_*.json"))
                for c in json.loads(Path(f).read_text()) for s in c["sims"])
    figs = "\n".join(f"<figure><img alt='{a}' src='data:image/png;base64,{b}'></figure>"
                     for a, b in imgs)
    html = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Airline Sweep Pilot</title><style>
:root{{--bg:#fcfcfb;--ink:#0b0b0b;--muted:#52514e;--line:#e4e3df;--card:#fff}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#1a1a19;--ink:#f0efec;--muted:#c3c2b7;--line:#3a3936;--card:#232322}}}}
:root[data-theme=dark]{{--bg:#1a1a19;--ink:#f0efec;--muted:#c3c2b7;--line:#3a3936;--card:#232322}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 20px}}
.rec{{background:var(--card);border:1px solid var(--line);border-left:4px solid #2a78d6;padding:12px 16px;border-radius:6px;margin-bottom:12px}}
.note{{color:var(--muted);font-size:13px;margin-bottom:24px}}
.tw{{overflow-x:auto;margin-bottom:28px}} table{{border-collapse:collapse;font-size:13px;white-space:nowrap;font-variant-numeric:tabular-nums}}
th,td{{padding:6px 10px;border-bottom:1px solid var(--line);text-align:right}} th:nth-child(-n+3),td:nth-child(-n+3){{text-align:left}}
th{{color:var(--muted);font-weight:600}} .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
figure{{margin:0 0 20px;background:#fcfcfb;border:1px solid var(--line);border-radius:6px;overflow:hidden}} img{{width:100%;display:block}}
</style></head><body><main>
<h1>tau2-bench airline: model/parameter pilot</h1>
<p class=sub>Tasks 0, 6, 11, 17, 31 · 1 trial · user simulator fixed on claude-haiku-4-5 · agent prompt caching on in every cell · pilot spend ≈ ${total:.2f} (agent + user sim, excl. sanity checks)</p>
<div class=rec><strong>Recommendation (pilot):</strong> {rec}</div>
<p class=note>Small pilot: {excl_note}one trial, so one task = {100 // max(n, 1)} percentage points of pass rate and differences of one or two tasks are within noise. Costs are agent-side with prompt caching; latency is summed agent generation time (excludes user-sim and tool time).</p>
<div class=tw><table><thead><tr><th>Model</th><th>Thinking</th><th>Effort</th><th>Passed</th><th>Pass rate</th><th>Cost/task</th><th>Cost/success</th><th>Out tok/task</th><th>In tok/task</th><th>Turns</th><th>Gen time/task</th><th>p50 gen time</th><th>Time/success</th><th>User-sim $/task</th></tr></thead>
<tbody>{trs}</tbody></table></div>
{figs}
</main></body></html>"""
    (HERE / "sweep_report.html").write_text(html)


def main():
    rows = load()
    imgs = [
        ("Pass rate vs output tokens", figure(rows, "out_tok", "Avg output tokens per task", "sweep_tokens.png")),
        ("Pass rate vs agent cost", figure(rows, "cost", "Avg agent cost per task", "sweep_cost.png")),
        ("Pass rate vs latency", figure(rows, "secs", "Avg agent generation time per task (s)", "sweep_latency.png")),
    ]
    rec_path = HERE / "recommendation.txt"
    rec = rec_path.read_text().strip() if rec_path.exists() else "(pending)"
    report(rows, imgs, rec)
    for r in rows:
        print(f"{r['model']:18} t{r['thinking']:3} e{str(r['effort']):5} "
              f"{r['passes']}/{r['n']} ${r['cost']:.3f}/task "
              f"cps={fmt_money(r['cost_per_success'])} out={r['out_tok']:.0f} "
              f"gen={r['secs']:.1f}s complete={r['complete']}")


if __name__ == "__main__":
    main()
