#!/usr/bin/env python3
"""Generate one tournament_nb saturation config for a (nodes, msgsize) cell.

Used by run_sweep.sh to materialize the 2D sweep on the fly (node count x message
size) instead of committing ~80 static files. maxsamples is sized to the node
count so the per-node LRU ring doesn't wrap ((N-1)*iters samples). The big-job
DCGP QOS is added automatically above --qos-min-nodes.
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
    p.add_argument("-o", "--out", required=True)
    a = p.parse_args()

    n = a.nodes
    maxsamples = (n - 1) * a.iters + 200      # avoid ring-buffer wrap
    go = {
        "numnodes": str(n), "ppn": "1", "allocationmode": "l",
        "timeout": a.timeout, "walltime": a.walltime, "outformat": "csv",
        "name": f"tournament_sat_n{n}_m{a.msgsize}",
    }
    if n >= a.qos_min_nodes:
        go["sbatch_directives"] = ["--qos=dcgp_qos_bprod", "--cpus-per-task=112"]
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
