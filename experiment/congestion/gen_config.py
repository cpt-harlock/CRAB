#!/usr/bin/env python3
"""Generate one congestion config for a (nodes, victim-msg, aggressor-msg) cell.

baseline + loaded experiments share the partitioned (50:50 interleaved)
allocation, so the victim runs on the same nodes in both. N splits into N/2
victim + N/2 aggressor — needs N a multiple of 4 (so N/2 is an even,
tournament-valid rank count).

In the loaded experiment the aggressor LEADS: it starts at t=0 and the victim is
delayed by --aggr-lead seconds, so the victim measures against an already-
congested fabric rather than the aggressor's ramp-up.

Victim/aggressor are selectable (--victim / --aggressor):
  victims    : tournament (all-pairs bandwidth) | allgather (ring, directed)
  aggressors : alltoall (bisection stress)      | incast (all -> one receiver)

Either message size can be the swept axis: the dose-response driver sweeps
--aggr-msgsize (fixed victim); the paper-repro driver sweeps --victim-msgsize
(fixed aggressor). Both sizes are encoded in the run name (vm.../am...).

Scheduler directives: by default the big-job DCGP QOS is auto-added at
>=--qos-min-nodes; pass --no-auto-qos and one or more --sbatch '<flag>' to target
a different partition/account/QOS (e.g. Leonardo Booster).
"""
import argparse
import json

# name -> (wrapper, tag, kind, arg template). kind sizes maxsamples:
#   pairwise   -> (victim_nodes-1)*iters samples ; collective -> ~iters samples.
VICTIMS = {
    "tournament": ("tournament_nb.py", "tour", "pairwise",
                   "-msgsize {vmsg} -window 64 -iter {iters} -warmup {warmup} "
                   "-maxsamples {vmax}"),
    "allgather":  ("agtr_comm_only.py", "agtr", "collective",
                   "-msgsize {vmsg} -iter {iters} -warmup {warmup} "
                   "-maxsamples {vmax}"),
}
AGGRESSORS = {
    "alltoall": ("a2a_nb.py", "a2a", "-msgsize {amsg} -endl"),
    "incast":   ("inc_nb.py", "inc", "-msgsize {amsg} -endl"),  # all -> rank 0
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--nodes", type=int, required=True)
    p.add_argument("--victim-msgsize", type=int, default=4194304)
    p.add_argument("--aggr-msgsize", type=int, required=True)
    p.add_argument("--victim", choices=list(VICTIMS), default="tournament")
    p.add_argument("--aggressor", choices=list(AGGRESSORS), default="alltoall")
    p.add_argument("--iters", type=int, default=10)
    p.add_argument("--warmup", type=int, default=0)
    p.add_argument("--aggr-lead", type=int, default=10,
                   help="seconds the aggressor leads the victim in the loaded "
                        "experiment: the aggressor starts at t=0 and the victim "
                        "is delayed by this much, so the fabric is already "
                        "congested when the victim's measurement begins (0=both "
                        "start together)")
    p.add_argument("--walltime", default="00:30:00")
    p.add_argument("--timeout", default="1500.0")
    p.add_argument("--qos-min-nodes", type=int, default=32)
    p.add_argument("--no-auto-qos", action="store_true",
                   help="skip the automatic dcgp_qos_bprod + cpus-per-task")
    p.add_argument("--sbatch", action="append", default=[],
                   help="extra #SBATCH directive (repeatable), e.g. "
                        "--sbatch=--partition=boost_usr_prod")
    p.add_argument("-o", "--out", required=True)
    a = p.parse_args()

    n = a.nodes
    if n % 4 != 0:
        raise SystemExit(f"nodes must be a multiple of 4 (got {n}): victim count "
                         "N/2 must be an even, tournament-valid rank count")
    victim_nodes = n // 2
    vpath, vtag, vkind, vtmpl = VICTIMS[a.victim]
    apath, atag, atmpl = AGGRESSORS[a.aggressor]

    samples = ((victim_nodes - 1) * a.iters if vkind == "pairwise" else a.iters)
    vmax = samples + a.warmup + 200       # avoid LRU ring wrap

    sbatch = list(a.sbatch)
    if not a.no_auto_qos and n >= a.qos_min_nodes:
        sbatch += ["--qos=dcgp_qos_bprod", "--cpus-per-task=112"]
    go = {
        "numnodes": str(n), "ppn": "1", "allocationmode": "p",
        "partitionsplit": "50:50", "partitionlayout": "i",
        "timeout": a.timeout, "walltime": a.walltime, "outformat": "csv",
        "name": f"congestion_{vtag}_{atag}_n{n}_vm{a.victim_msgsize}_am{a.aggr_msgsize}",
    }
    if sbatch:
        go["sbatch_directives"] = sbatch

    victim = {
        "path": vpath,
        "args": vtmpl.format(vmsg=a.victim_msgsize, iters=a.iters,
                             warmup=a.warmup, vmax=vmax),
        "collect": True, "start": "0", "end": "", "partition": 0,
    }
    aggressor = {
        "path": apath,
        "args": atmpl.format(amsg=a.aggr_msgsize),
        "collect": False, "start": "0", "end": "f", "partition": 1,
    }
    # Loaded experiment: aggressor leads. It starts at t=0; the victim is delayed
    # by aggr-lead so it measures against an already-saturated fabric (not the
    # aggressor's ramp-up). Baseline victim is undelayed (no aggressor to wait
    # for), so its measurement is unchanged -> the baseline-vs-loaded diff stays
    # clean. The engine still kills the endless aggressor when the victim ends.
    loaded_victim = dict(victim)
    loaded_victim["start"] = str(a.aggr_lead)
    cfg = {
        "global_options": go,
        "experiments": {
            "baseline": {"apps": {"0": dict(victim)}},
            "loaded": {"apps": {"0": loaded_victim, "1": aggressor}},
        },
    }
    with open(a.out, "w") as fh:
        json.dump(cfg, fh, indent=2)
    print(a.out)


if __name__ == "__main__":
    main()
