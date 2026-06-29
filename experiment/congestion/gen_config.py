#!/usr/bin/env python3
"""Generate one congestion config for a (nodes, aggressor-msgsize) cell.

victim runs at a fixed saturating size; aggressor runs -endl at the swept message
size (the dose-response knob). baseline + loaded experiments share the
partitioned (50:50 interleaved) allocation, so the victim runs on the same nodes
in both. N splits into N/2 victim + N/2 aggressor — needs N a multiple of 4 (so
N/2 is an even, tournament-valid rank count).

Victim/aggressor are selectable (--victim / --aggressor):
  victims    : tournament (all-pairs bandwidth) | allgather (ring, directed)
  aggressors : alltoall (bisection stress)      | incast (all -> one receiver)
"""
import argparse
import json

# name -> (wrapper, tag, arg template). {vmsg}/{amsg}=msg size, {iters}, {vmax}.
VICTIMS = {
    "tournament": ("tournament_nb.py", "tour",
                   "-msgsize {vmsg} -window 64 -iter {iters} -maxsamples {vmax}"),
    "allgather":  ("agtr_comm_only.py", "agtr",
                   "-msgsize {vmsg} -iter {iters} -maxsamples {vmax}"),
}
AGGRESSORS = {
    "alltoall": ("a2a_nb.py", "a2a", "-msgsize {amsg} -endl"),
    "incast":   ("inc_nb.py", "inc", "-msgsize {amsg} -endl"),  # all -> rank 0
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--nodes", type=int, required=True)
    p.add_argument("--aggr-msgsize", type=int, required=True)
    p.add_argument("--victim-msgsize", type=int, default=4194304)
    p.add_argument("--victim", choices=list(VICTIMS), default="tournament")
    p.add_argument("--aggressor", choices=list(AGGRESSORS), default="alltoall")
    p.add_argument("--iters", type=int, default=10)
    p.add_argument("--walltime", default="00:30:00")
    p.add_argument("--timeout", default="1500.0")
    p.add_argument("--qos-min-nodes", type=int, default=32)
    p.add_argument("-o", "--out", required=True)
    a = p.parse_args()

    n = a.nodes
    if n % 4 != 0:
        raise SystemExit(f"nodes must be a multiple of 4 (got {n}): victim count "
                         "N/2 must be an even, tournament-valid rank count")
    victim_nodes = n // 2
    vmax = (victim_nodes - 1) * a.iters + 200
    vpath, vtag, vtmpl = VICTIMS[a.victim]
    apath, atag, atmpl = AGGRESSORS[a.aggressor]
    go = {
        "numnodes": str(n), "ppn": "1", "allocationmode": "p",
        "partitionsplit": "50:50", "partitionlayout": "i",
        "timeout": a.timeout, "walltime": a.walltime, "outformat": "csv",
        "name": f"congestion_{vtag}_{atag}_n{n}_m{a.aggr_msgsize}",
    }
    if n >= a.qos_min_nodes:
        go["sbatch_directives"] = ["--qos=dcgp_qos_bprod", "--cpus-per-task=112"]

    victim = {
        "path": vpath,
        "args": vtmpl.format(vmsg=a.victim_msgsize, iters=a.iters, vmax=vmax),
        "collect": True, "start": "0", "end": "", "partition": 0,
    }
    aggressor = {
        "path": apath,
        "args": atmpl.format(amsg=a.aggr_msgsize),
        "collect": False, "start": "0", "end": "f", "partition": 1,
    }
    cfg = {
        "global_options": go,
        "experiments": {
            "baseline": {"apps": {"0": dict(victim)}},
            "loaded": {"apps": {"0": dict(victim), "1": aggressor}},
        },
    }
    with open(a.out, "w") as fh:
        json.dump(cfg, fh, indent=2)
    print(a.out)


if __name__ == "__main__":
    main()
