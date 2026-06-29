#!/usr/bin/env python3
"""Command-line entry for the tournament_nb result analyzer.

Reports per-node / per-round / overall bandwidth & latency, annotates each
pairing with topology distance, summarizes the per-round topology mix, flags
under-performing nodes, and renders text + plots.

Invoked as ``cinetic analyze <run_dir | exp_dir> --topology …`` (or via the
``tournament_analyzer.py`` compatibility shim). See PLAN_RESULT_ANALYZER.md.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from cinetic.analysis import compare, congestion, context, fabric, health, metrics, outliers as outl, params as prm, parse, topo
from cinetic.analysis import report_plot, report_text


def _find_exp_dirs(path: str) -> list[str]:
    """Accept either an exp dir (has node_*.csv) or a run dir (has exp subdirs)."""
    if glob.glob(os.path.join(path, "node_*.csv")):
        return [path]
    subs = sorted(d for d in glob.glob(os.path.join(path, "*"))
                  if os.path.isdir(d) and glob.glob(os.path.join(d, "node_*.csv")))
    return subs


def _default_topology(run_dir: str) -> str | None:
    """Look for a topology JSON shipped with the repo (best-effort default)."""
    # this module lives at src/cinetic/analysis/cli.py -> repo root is three up
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    cand = os.path.join(repo, "topologies", "leonardo.json")
    return cand if os.path.isfile(cand) else None


def _resolve_expected_bw(exp_dir: str, args) -> float | None:
    """Nominal per-node bandwidth (GB/s) for the absolute sanity-check rule.

    CLI ``--expected-bw`` wins; otherwise fall back to ``CINETIC_EXPECTED_BW`` in
    the run's ``environment.json`` so a system preset can set it once. ``None``
    when neither is present (the absolute rule is then simply skipped)."""
    if getattr(args, "expected_bw", None) is not None:
        return float(args.expected_bw)
    run_dir = os.path.dirname(exp_dir.rstrip(os.sep))
    for env_path in (os.path.join(exp_dir, "environment.json"),
                     os.path.join(run_dir, "environment.json")):
        if not os.path.isfile(env_path):
            continue
        try:
            env = json.load(open(env_path))
        except (OSError, json.JSONDecodeError):
            continue
        val = env.get("CINETIC_EXPECTED_BW")
        if val not in (None, ""):
            try:
                return float(val)
            except (TypeError, ValueError):
                print(f"[warn] CINETIC_EXPECTED_BW={val!r} is not a number; "
                      "ignoring", file=sys.stderr)
        break
    return None


def analyze_exp_dir(exp_dir: str, args) -> int:
    """Analyze every app in *exp_dir* (one report set per app).

    A multi-app experiment namespaces files by app id; each app is a distinct
    benchmark and is analyzed independently. With more than one app, outputs go
    to ``analysis/app_<id>/`` so they don't overwrite each other."""
    app_ids = parse.app_ids_in_dir(exp_dir)
    multi = len(app_ids) > 1
    ctx = context.load_context(exp_dir)   # roles/system (degrades if no config)
    rc = 1
    built_all = []                        # kept for the fabric pass (goal 4)
    for app_id in app_ids:
        sub = None
        if multi:
            sub = f"app_{app_id}" if app_id is not None else "app_legacy"
        built = _build_analysis(exp_dir, app_id, args, ctx)
        if built is None:
            if app_id is not None:
                print(f"[skip] {exp_dir} (app {app_id}): no parseable node files",
                      file=sys.stderr)
            continue
        _report_analysis(exp_dir, sub, args, ctx, built)
        built_all.append(built)
        rc = 0

    # fabric load attribution (goal 4): combines ALL collecting apps of this
    # experiment, since they shared the fabric concurrently.
    if getattr(args, "fabric", False) and built_all:
        _run_fabric(exp_dir, args, built_all)
    return rc


def _build_analysis(exp_dir: str, app_id, args, ctx=None):
    """Parse + analyze one app, annotated with role/context. Returns
    ``(analysis, outliers, topo_path)`` or ``None`` when there are no node files.
    Shared by the per-app report path and the congestion comparison."""
    ds = parse.parse_exp_dir(exp_dir, app_id=app_id)
    if not ds.matches:
        return None

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
    # annotate with role/system from the experiment context (no-op if no config)
    app = ctx.app(app_id) if ctx is not None else None
    if app is not None:
        an.app_id = app.app_id
        an.role = app.role.value
        an.output_kind = app.output_kind
    elif app_id is not None:
        an.app_id = str(app_id)
    an.window_timeouts = health.window_timeouts(exp_dir, app_id)
    expected_bw = _resolve_expected_bw(exp_dir, args)
    ol = outl.detect(an.node_bw_median, k=args.slow_k, frac=args.slow_frac,
                     min_nodes=args.min_nodes, expected_bw=expected_bw,
                     expected_frac=args.expected_frac)
    return an, ol, topo_path


def _report_analysis(exp_dir: str, subdir, args, ctx, built) -> None:
    """Write/print the per-app report set for an already-built analysis."""
    an, ol, topo_path = built

    report = report_text.format_report(an, ol, topo_path, context=ctx)
    if subdir:
        print(f"\n################ {subdir} ################")
    print(report)

    # detailed per-peer and per-round-per-node views (verbose: written to files
    # always; echoed to stdout only with --detail)
    peer_profiles = report_text.format_peer_profiles(an)
    per_round_per_node = report_text.format_per_round_per_node(an)
    if args.detail:
        print("\n" + peer_profiles)
        print("\n" + per_round_per_node)

    outdir = args.outdir or os.path.join(exp_dir, "analysis")
    if subdir:
        outdir = os.path.join(outdir, subdir)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "report.txt"), "w") as fh:
        fh.write(report + "\n")
    with open(os.path.join(outdir, "peer_profiles.txt"), "w") as fh:
        fh.write(peer_profiles + "\n")
    with open(os.path.join(outdir, "per_round_per_node.txt"), "w") as fh:
        fh.write(per_round_per_node + "\n")
    if args.json:
        with open(os.path.join(outdir, "summary.json"), "w") as fh:
            json.dump(report_text.build_summary(an, ol, context=ctx), fh, indent=2)

    if not args.no_plots:
        try:
            paths = report_plot.generate_plots(an, ol, outdir, show=args.show,
                                               topo_graph=args.topo_graph)
            print(f"\n[plots] wrote {len(paths)} figure(s) to {outdir}",
                  file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] plotting failed: {exc}", file=sys.stderr)


def _run_fabric(exp_dir: str, args, built_all) -> None:
    """Attribute switch/link load across all of an experiment's apps (goal 4)."""
    topo_path = args.topology or _default_topology(os.path.dirname(exp_dir))
    topology = topo.load_topology(topo_path) if topo_path else None
    if topology is None:
        print("[fabric] no topology — skipping link attribution", file=sys.stderr)
        return
    analyses = [b[0] for b in built_all]
    fl = fabric.attribute(analyses, topology)
    if fl is None:
        print("[fabric] <80% of hosts resolve in the topology — skipping "
              "(wrong topology file?)", file=sys.stderr)
        return
    text = fabric.format_fabric(fl, top_n=args.hotspots)
    print("\n" + text)
    outdir = args.outdir or os.path.join(exp_dir, "analysis")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "fabric.txt"), "w") as fh:
        fh.write(text + "\n")
    if args.json:
        with open(os.path.join(outdir, "fabric.json"), "w") as fh:
            json.dump(fabric.build_fabric_summary(fl), fh, indent=2)
    if not args.no_plots:
        try:
            report_plot.plot_fabric(fl, os.path.join(outdir, "fabric_load.png"),
                                    top_n=args.hotspots)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] fabric plot failed: {exc}", file=sys.stderr)
    print(f"[fabric] wrote attribution to {outdir}", file=sys.stderr)


def _parse_app_id(exp_dir: str, app):
    """The app id to hand :func:`parse.parse_exp_dir`: the config id when its
    files are app-prefixed, else ``None`` for a legacy un-prefixed dump."""
    if glob.glob(os.path.join(exp_dir, f"node_app{app.app_id}_*.csv")):
        return app.app_id
    return None


def _collect_victims(exp_dirs):
    """[(exp_dir, ctx, AppInfo), ...] for every victim app in *exp_dirs*."""
    out = []
    for d in exp_dirs:
        c = context.load_context(d)
        for app in c.victims:
            out.append((d, c, app))
    return out


def run_congestion(exp_dirs, args) -> int:
    """Pair victim apps in LOADED experiments with a baseline of the same
    benchmark and report degradation. Best-effort: silently does nothing when no
    baseline+loaded pair can be found. Returns 0 if at least one pair reported."""
    loaded = []
    for d in exp_dirs:
        c = context.load_context(d)
        if c.is_loaded:
            for app in c.victims:
                loaded.append((d, c, app))
    if not loaded:
        return 1

    if args.baseline:
        base_dirs = _find_exp_dirs(args.baseline)
        if not base_dirs:
            print(f"[warn] --baseline {args.baseline}: no node files found",
                  file=sys.stderr)
            return 1
    else:
        base_dirs = [d for d in exp_dirs if context.load_context(d).is_baseline]
    baseline_victims = _collect_victims(base_dirs)
    if not baseline_victims:
        return 1

    results = []
    for (dL, cL, appL) in loaded:
        match = next(((dB, cB, appB) for (dB, cB, appB) in baseline_victims
                      if appB.wrapper_name == appL.wrapper_name), None)
        if match is None:
            continue
        dB, cB, appB = match
        builtB = _build_analysis(dB, _parse_app_id(dB, appB), args, cB)
        builtL = _build_analysis(dL, _parse_app_id(dL, appL), args, cL)
        if builtB is None or builtL is None:
            continue
        cr = congestion.compute_congestion(
            builtB[0], builtL[0],
            baseline_label=f"{cB.exp_id} (app {appB.app_id})",
            loaded_label=f"{cL.exp_id} (app {appL.app_id}, +aggressors)",
            victim_benchmark=appL.wrapper_name)
        results.append(cr)

    if not results:
        return 1

    # run-level output dir (parent of the exp dirs)
    run_dir = os.path.dirname(os.path.abspath(exp_dirs[0]))
    outdir = args.outdir or os.path.join(run_dir, "analysis")
    os.makedirs(outdir, exist_ok=True)

    texts, summaries = [], []
    for cr in results:
        text = congestion.format_congestion(cr)
        print("\n" + text)
        texts.append(text)
        summaries.append(congestion.build_congestion_summary(cr))
        if not args.no_plots:
            try:
                report_plot.plot_congestion(
                    cr, os.path.join(outdir, f"congestion_app{cr.victim_app}.png"))
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] congestion plot failed: {exc}", file=sys.stderr)

    with open(os.path.join(outdir, "congestion.txt"), "w") as fh:
        fh.write("\n\n".join(texts) + "\n")
    if args.json:
        with open(os.path.join(outdir, "congestion.json"), "w") as fh:
            json.dump(summaries, fh, indent=2)
    print(f"\n[congestion] wrote {len(results)} comparison(s) to {outdir}",
          file=sys.stderr)
    return 0


def _select_compare_analysis(d: str, args):
    """One (Analysis, label_hint, ts) per <dir> for `compare`: prefer a victim
    app, else the first app of the first experiment with node files."""
    exp_dirs = _find_exp_dirs(d)
    if not exp_dirs:
        return None
    chosen = None  # (exp_dir, ctx, app_or_None, app_id)
    for ed in exp_dirs:
        ctx = context.load_context(ed)
        victims = ctx.victims
        if victims:
            app = victims[0]
            chosen = (ed, ctx, app, _parse_app_id(ed, app))
            break
        if chosen is None:
            ids = parse.app_ids_in_dir(ed)
            app = ctx.app(ids[0]) if ids else None
            chosen = (ed, ctx, app, ids[0] if ids else None)
    if chosen is None:
        return None
    ed, ctx, app, app_id = chosen
    built = _build_analysis(ed, app_id, args, ctx)
    if built is None:
        return None
    # x ordering: parse a timestamp from the dir (or its parent) basename
    ts = (compare.parse_timestamp(os.path.basename(os.path.abspath(d)))
          or compare.parse_timestamp(os.path.basename(os.path.dirname(
              os.path.abspath(ed)))))
    return built[0], ts


def main_compare(argv) -> int:
    ap = argparse.ArgumentParser(
        prog="cinetic analyze compare",
        description="Cross-experiment comparison of N run/exp dirs.")
    ap.add_argument("dirs", nargs="+", help="run/exp dirs to compare (>=2)")
    ap.add_argument("--label", action="append", default=[],
                    help="series label (repeat, in dir order)")
    ap.add_argument("--x", help="ordering for trend: 'index', 'timestamp', or a "
                    "comma-separated list of numbers (one per dir)")
    ap.add_argument("--bw-relative", action="store_true", dest="bw_relative",
                    help="normalize bandwidth to each series' own median")
    ap.add_argument("--topology")
    ap.add_argument("--msg-size", type=int, dest="msg_size")
    ap.add_argument("--window", type=int)
    ap.add_argument("--granularity", type=int)
    ap.add_argument("--outdir", help="default: <first dir>/analysis")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-plots", action="store_true")
    ap.add_argument("--slow-k", type=float, default=3.0)
    ap.add_argument("--slow-frac", type=float, default=0.7)
    ap.add_argument("--min-nodes", type=int, default=8)
    ap.add_argument("--expected-bw", type=float, dest="expected_bw",
                    help="nominal per-node bandwidth GB/s (absolute rule); "
                         "falls back to CINETIC_EXPECTED_BW")
    ap.add_argument("--expected-frac", type=float, default=0.8,
                    dest="expected_frac")
    args = ap.parse_args(argv)
    if len(args.dirs) < 2:
        print("error: compare needs >= 2 dirs", file=sys.stderr)
        return 2

    picked = []   # (dir, Analysis, ts)
    for d in args.dirs:
        sel = _select_compare_analysis(d, args)
        if sel is None:
            print(f"[skip] {d}: no analyzable app", file=sys.stderr)
            continue
        picked.append((d, sel[0], sel[1]))
    if len(picked) < 2:
        print("error: fewer than 2 comparable series", file=sys.stderr)
        return 2

    # x values for the trend
    xvals = _resolve_x(args.x, [p[0] for p in picked], [p[2] for p in picked])
    series = []
    for i, (d, an, _ts) in enumerate(picked):
        label = args.label[i] if i < len(args.label) \
            else os.path.basename(os.path.abspath(d))
        series.append(compare.series_from_analysis(
            label, an, x=(xvals[i] if xvals else None)))

    cr = compare.compare(series, relative=args.bw_relative)
    text = compare.format_comparison(cr)
    print(text)

    outdir = args.outdir or os.path.join(os.path.abspath(args.dirs[0]), "analysis")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "comparison.txt"), "w") as fh:
        fh.write(text + "\n")
    if args.json:
        with open(os.path.join(outdir, "comparison.json"), "w") as fh:
            json.dump(compare.build_comparison_summary(cr), fh, indent=2)
    if not args.no_plots:
        try:
            report_plot.plot_comparison(cr, os.path.join(outdir, "comparison.png"))
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] comparison plot failed: {exc}", file=sys.stderr)
    print(f"\n[compare] wrote comparison to {outdir}", file=sys.stderr)
    return 0


def _resolve_x(spec, dirs, timestamps):
    """Turn the --x spec into per-series x values, or None if unavailable."""
    if spec == "index":
        return list(range(len(dirs)))
    if spec == "timestamp":
        return timestamps if all(t is not None for t in timestamps) else None
    if spec:
        try:
            xs = [float(v) for v in spec.split(",")]
            return xs if len(xs) == len(dirs) else None
        except ValueError:
            return None
    # no explicit spec: use timestamps if every dir has one (enables trend)
    return timestamps if all(t is not None for t in timestamps) else None


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "compare":
        return main_compare(argv[1:])

    ap = argparse.ArgumentParser(
        prog="cinetic analyze", description=__doc__,
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
    ap.add_argument("--expected-bw", type=float, dest="expected_bw",
                    help="nominal per-node bandwidth (GB/s, full-duplex busbw) for "
                         "the absolute sanity-check rule; catches fabric-wide "
                         "degradation. Falls back to CINETIC_EXPECTED_BW in "
                         "environment.json")
    ap.add_argument("--expected-frac", type=float, default=0.8,
                    dest="expected_frac",
                    help="flag nodes (and the run) below frac*expected-bw "
                         "(default 0.8)")
    ap.add_argument("--baseline",
                    help="baseline run/exp dir for congestion comparison "
                         "(default: auto-detect a victim-only experiment)")
    ap.add_argument("--no-congestion", action="store_true",
                    help="skip the victim-vs-baseline congestion comparison")
    ap.add_argument("--fabric", action="store_true",
                    help="attribute per-switch/per-link load (needs --topology)")
    ap.add_argument("--hotspots", type=int, default=15,
                    help="top-N congested links/switches to report (default 15)")
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

    # congestion impact (goal 1): best-effort, only when a baseline+loaded pair
    # exists (in-run auto-detect, or via --baseline).
    if not args.no_congestion:
        run_congestion(exp_dirs, args)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
