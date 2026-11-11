"""Resumable pilot sweep over agent model x thinking x effort for tau2 airline.

Usage: .venv/bin/python sweep/sweep_runner.py
Env:   SWEEP_TRIAL (default 0), SWEEP_BUDGET_USD (hard stop, default 3.0)

A cell is skipped only if its results.json holds all expected task IDs.
Partial cells are resumed by tau2 (--auto-resume), so finished sims are not re-paid.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAU2 = str(ROOT / ".venv/bin/tau2")
SIM_DIR = ROOT / "data/simulations"
OUT_DIR = Path(__file__).resolve().parent

TASK_IDS = os.environ.get("SWEEP_TASK_IDS", "0 6 11 17 31").split()
# e.g. "--communicate-scorer substring"; SUFFIX keeps reruns in separate dirs
EXTRA_ARGS = os.environ.get("SWEEP_EXTRA_ARGS", "").split()
SUFFIX = os.environ.get("SWEEP_SLUG_SUFFIX", "")
USER_LLM = "anthropic/claude-haiku-4-5"
TRIAL = os.environ.get("SWEEP_TRIAL", "0")
BUDGET = float(os.environ.get("SWEEP_BUDGET_USD", "3.0"))

ADAPTIVE = '{"type":"adaptive"}'
CELLS = [
    # model, thinking label, thinking json, effort
    ("claude-haiku-4-5", "toff", "", ""),
    ("claude-haiku-4-5", "ton", '{"type":"enabled","budget_tokens":4096}', ""),
    ("claude-sonnet-4-6", "toff", "", "low"),
    ("claude-sonnet-4-6", "ton", ADAPTIVE, "high"),
    ("claude-opus-4-7", "toff", "", "low"),
    ("claude-opus-4-7", "ton", ADAPTIVE, "high"),
]


def slug(model, tl, effort):
    short = model.replace("claude-", "").replace("-", "")
    return f"pilot_{short}_{tl}_e{effort or 'none'}_tr{TRIAL}{SUFFIX}"


def sim_metrics(s):
    a = [m for m in s["messages"] if m.get("role") == "assistant" and m.get("usage")]
    u = [m for m in s["messages"] if m.get("role") == "user" and m.get("cost")]
    lats = [m.get("generation_time_seconds") or 0.0 for m in a]
    return {
        "task_id": str(s["task_id"]),
        "passed": (s.get("reward_info") or {}).get("reward") == 1.0,
        "reward": (s.get("reward_info") or {}).get("reward"),
        "termination_reason": s.get("termination_reason"),
        "agent_cost": sum(m.get("cost") or 0.0 for m in a),
        "user_cost": sum(m["cost"] for m in u),
        "input_tokens": sum(m["usage"].get("prompt_tokens") or 0 for m in a),
        "output_tokens": sum(m["usage"].get("completion_tokens") or 0 for m in a),
        "agent_turns": len(a),
        "agent_generation_seconds": sum(lats),
    }


def load_cell(name):
    p = SIM_DIR / name / "results.json"
    if not p.exists():
        return []
    try:
        sims = json.loads(p.read_text()).get("simulations") or []
    except json.JSONDecodeError:
        return []
    return [sim_metrics(s) for s in sims]


def is_complete(rows):
    return set(TASK_IDS) <= {r["task_id"] for r in rows}


def spent(results):
    return sum(r["agent_cost"] + r["user_cost"] for c in results for r in c["sims"])


def main():
    out_path = OUT_DIR / f"sweep_results_{TRIAL}{SUFFIX}.json"
    results = []
    for model, tl, tj, effort in CELLS:
        name = slug(model, tl, effort)
        rows = load_cell(name)
        if is_complete(rows):
            print(f"[skip] {name} already complete", flush=True)
        else:
            so_far = spent(results)
            if so_far >= BUDGET:
                print(f"[stop] budget ${BUDGET:.2f} reached (${so_far:.2f})", flush=True)
                break
            env = {k: v for k, v in os.environ.items()
                   if k not in ("TAU2_AGENT_THINKING", "TAU2_AGENT_EFFORT")}
            env["TAU2_AGENT_PROMPT_CACHE"] = "1"
            if tj:
                env["TAU2_AGENT_THINKING"] = tj
            if effort:
                env["TAU2_AGENT_EFFORT"] = effort
            cmd = [TAU2, "run", "--domain", "airline",
                   "--agent-llm", f"anthropic/{model}", "--user-llm", USER_LLM,
                   "--task-ids", *TASK_IDS, "--num-trials", "1",
                   "--max-concurrency", "3", "--save-to", name, "--auto-resume", *EXTRA_ARGS]
            print(f"[run ] {name}", flush=True)
            proc = subprocess.run(cmd, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                  text=True)
            if proc.returncode != 0:
                print(f"[fail] {name} rc={proc.returncode}\n{proc.stderr[-2000:]}",
                      flush=True)
            rows = load_cell(name)
        results.append({"cell": name, "model": model, "thinking": tl[1:],
                        "thinking_json": tj, "effort": effort or None,
                        "complete": is_complete(rows), "sims": rows})
        out_path.write_text(json.dumps(results, indent=2))
        print(f"       n={len(rows)} pass={sum(r['passed'] for r in rows)} "
              f"agent=${sum(r['agent_cost'] for r in rows):.3f} "
              f"running total=${spent(results):.3f}", flush=True)
    print(f"done; wrote {out_path}; total ${spent(results):.3f}")
    return 0 if all(c["complete"] for c in results) and len(results) == len(CELLS) else 1


if __name__ == "__main__":
    sys.exit(main())
