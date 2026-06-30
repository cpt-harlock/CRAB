#!/usr/bin/env python3
"""Generate one tournament_nb saturation config for a (nodes, msgsize) cell.

Used by run_sweep.sh to materialize the 2D sweep on the fly (node count x message
size) instead of committing ~80 static files. maxsamples is sized to the node
count so the per-node LRU ring doesn't wrap ((N-1)*iters samples).

Scheduler directives: by default the big-job DCGP QOS is auto-added at
>=--qos-min-nodes; pass --no-auto-qos and one or more --sbatch '<flag>' to target
a different partition/account/QOS (e.g. Leonardo Booster). Mirrors the directive
surface of experiment/congestion/gen_config.py.
"""
import argparse
import json


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--nodes", type=int, required=True)
    p.add_argument("--msgsize", type=int, required=True)
    p.add_argument("--window", type=int, default=64)
    p.add_argument("--iters", type=int, default=10)
    p.add_argument("--walltime", default="00:30:00")
    p.add_argument("--timeout", default="1500.0")
    p.add_argument("--qos-min-nodes", type=int, default=32,
                   help="add dcgp_qos_bprod + cpus-per-task at/above this count")
    p.add_argument("--no-auto-qos", action="store_true",
                   help="skip the automatic dcgp_qos_bprod + cpus-per-task")
    p.add_argument("--sbatch", action="append", default=[],
                   help="extra #SBATCH directive (repeatable), e.g. "
                        "--sbatch=--partition=boost_usr_prod")
    p.add_argument("-o", "--out", required=True)
    a = p.parse_args()

    n = a.nodes
    maxsamples = (n - 1) * a.iters + 200      # avoid ring-buffer wrap
    go = {
        "numnodes": str(n), "ppn": "1", "allocationmode": "l",
        "timeout": a.timeout, "walltime": a.walltime, "outformat": "csv",
        "name": f"tournament_sat_n{n}_m{a.msgsize}",
    }
    sbatch = list(a.sbatch)
    if not a.no_auto_qos and n >= a.qos_min_nodes:
        sbatch += ["--qos=dcgp_qos_bprod", "--cpus-per-task=112"]
    if sbatch:
        go["sbatch_directives"] = sbatch
    cfg = {
        "global_options": go,
        "experiments": {"saturation": {"apps": {"0": {
            "path": "tournament_nb.py",
            "args": (f"-msgsize {a.msgsize} -window {a.window} "
                     f"-iter {a.iters} -maxsamples {maxsamples}"),
            "collect": True, "start": "0", "end": "",
        }}}},
    }
    with open(a.out, "w") as fh:
        json.dump(cfg, fh, indent=2)
    print(a.out)


if __name__ == "__main__":
    main()
