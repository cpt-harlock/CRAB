#!/usr/bin/env python3
"""Analyze tournament_nb per-node result files.

Reports per-node / per-round / overall bandwidth & latency, annotates each
pairing with topology distance, summarizes the per-round topology mix, flags
under-performing nodes, and renders text + plots.

Usage:
    python tournament_analyzer.py <run_dir | exp_dir> \
        --topology topologies/leonardo.json [--show] [--json]

See PLAN_RESULT_ANALYZER.md for the design.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

# Make the 'crab' package importable (mirrors cli.py / tui.py).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from crab.analysis import metrics, outliers as outl, params as prm, parse, topo
from crab.analysis import report_plot, report_text


def _find_exp_dirs(path: str) -> list[str]:
    """Accept either an exp dir (has node_*.csv) or a run dir (has exp subdirs)."""
    if glob.glob(os.path.join(path, "node_*.csv")):
        return [path]
    subs = sorted(d for d in glob.glob(os.path.join(path, "*"))
                  if os.path.isdir(d) and glob.glob(os.path.join(d, "node_*.csv")))
    return subs


def _default_topology(run_dir: str) -> str | None:
    """Look for a topology JSON shipped with the repo (best-effort default)."""
    repo = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(repo, "topologies", "leonardo.json")
    return cand if os.path.isfile(cand) else None


def analyze_exp_dir(exp_dir: str, args) -> int:
    ds = parse.parse_exp_dir(exp_dir)
    if not ds.matches:
        print(f"[skip] {exp_dir}: no parseable node files", file=sys.stderr)
        return 1

    params = prm.resolve_params(exp_dir, args.msg_size, args.window,
                                args.granularity)

    topo_path = args.topology or _default_topology(os.path.dirname(exp_dir))
    topology = None
    if topo_path:
        try:
            topology = topo.load_topology(topo_path)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            print(f"[warn] could not load topology {topo_path}: {exc}",
                  file=sys.stderr)
            topo_path = None
    resolver = topo.TopoResolver(topology=topology)

    an = metrics.analyze(ds, params, resolver)
    ol = outl.detect(an.node_bw_median, k=args.slow_k, frac=args.slow_frac,
                     min_nodes=args.min_nodes)

    report = report_text.format_report(an, ol, topo_path)
    print(report)

    # detailed per-peer and per-round-per-node views (verbose: written to files
    # always; echoed to stdout only with --detail)
    peer_profiles = report_text.format_peer_profiles(an)
    per_round_per_node = report_text.format_per_round_per_node(an)
    if args.detail:
        print("\n" + peer_profiles)
        print("\n" + per_round_per_node)

    outdir = args.outdir or os.path.join(exp_dir, "analysis")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "report.txt"), "w") as fh:
        fh.write(report + "\n")
    with open(os.path.join(outdir, "peer_profiles.txt"), "w") as fh:
        fh.write(peer_profiles + "\n")
    with open(os.path.join(outdir, "per_round_per_node.txt"), "w") as fh:
        fh.write(per_round_per_node + "\n")
    if args.json:
        with open(os.path.join(outdir, "summary.json"), "w") as fh:
            json.dump(report_text.build_summary(an, ol), fh, indent=2)

    if not args.no_plots:
        try:
            paths = report_plot.generate_plots(an, ol, outdir, show=args.show,
                                               topo_graph=args.topo_graph)
            print(f"\n[plots] wrote {len(paths)} figure(s) to {outdir}",
                  file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] plotting failed: {exc}", file=sys.stderr)

    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="run dir or experiment dir with node_*.csv")
    ap.add_argument("--topology", help="topology JSON (e.g. topologies/leonardo.json)")
    ap.add_argument("--msg-size", type=int, dest="msg_size")
    ap.add_argument("--window", type=int)
    ap.add_argument("--granularity", type=int)
    ap.add_argument("--outdir", help="default: <exp_dir>/analysis")
    ap.add_argument("--json", action="store_true", help="also write summary.json")
    ap.add_argument("--show", action="store_true", help="display plots interactively")
    ap.add_argument("--no-plots", action="store_true", help="skip figures")
    ap.add_argument("--detail", action="store_true",
                    help="also print the full peer-profile and per-round-per-node "
                         "tables to stdout (always written to files)")
    ap.add_argument("--topo-graph", action="store_true", dest="topo_graph",
                    help="also draw the topology node-link diagram")
    ap.add_argument("--slow-k", type=float, default=3.0,
                    help="robust z-score threshold (default 3.0)")
    ap.add_argument("--slow-frac", type=float, default=0.7,
                    help="absolute slow threshold = frac*median (default 0.7)")
    ap.add_argument("--min-nodes", type=int, default=8,
                    help="below this node count, demote z-score (default 8)")
    args = ap.parse_args(argv)

    exp_dirs = _find_exp_dirs(args.path)
    if not exp_dirs:
        print(f"error: no node_*.csv found under {args.path}", file=sys.stderr)
        return 2

    rc = 0
    for d in exp_dirs:
        if len(exp_dirs) > 1:
            print(f"\n########## {d} ##########")
        rc |= analyze_exp_dir(d, args)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
