# Tournament bandwidth saturation sweep (Leonardo DCGP)

Runs `benchmarks/blink/tournament_nb` across a **2D grid** of node count × message
size, to measure per-node pairwise bandwidth (and its topology breakdown) over
the latency→bandwidth transition as the job scales.

## What it does

- One `cinetic run` per `(nodes, msgsize)` cell (a node sweep can't share a Slurm
  allocation), preset `leonardo` (slurm backend, `dcgp_usr_prod`). Configs are
  **generated on the fly** by `gen_config.py` into `generated/` (gitignored) — no
  ~80 static files.
- `tournament_nb -msgsize <M> -window 64`, `ppn=1` so each rank owns its node's
  link (per-node bandwidth). `maxsamples` is sized per node count so the LRU ring
  doesn't wrap ((N−1)·iters). The big-job DCGP QOS (`dcgp_qos_bprod` +
  `--cpus-per-task=112`) is added automatically at ≥32 nodes.

Axes (override via env vars on either script):
- `NODE_COUNTS="2 4 8 16 32 64 128 256 512 1024"` (even, tournament needs an even
  rank count).
- `MSG_SIZES="8 64 512 4096 32768 262144 2097152 16777216"` (8 B → 16 MB, ×8).

## Run

```bash
# 0. (on Leonardo) build the benchmark under the SAME modules the preset loads:
module purge && module load openmpi
( cd benchmarks/blink && make )

# 1. submit the full grid (one Slurm job per (nodes, msgsize) cell)
experiment/saturation_sweep/run_sweep.sh
#    …or a subset, e.g. a quick smoke test:
NODE_COUNTS="2 4 8" MSG_SIZES="4096 262144" experiment/saturation_sweep/run_sweep.sh

# 2. after the jobs finish: per-run reports + a bandwidth-vs-nodes `compare`
#    for each message size
experiment/saturation_sweep/analyze_sweep.sh
```

Per-run results land under `data/leonardo/tournament_sat_n<N>_m<M>_<timestamp>/`.
The per-message-size scaling curves (overall/by-locality bandwidth vs node count,
with a trend) are written under
`data/leonardo/_sweep_analysis/saturation/m<M>/comparison.{txt,json,png}`.

> The full grid is large (10×8 = 80 jobs) and the big cells (≥512 nodes, ≥2 MB)
> are heavy; submit a subset first and confirm QOS limits allow your largest node
> count. The original 1D per-node configs (`configs/tournament_N*.json`) remain as
> documented examples.

### Absolute sanity check (catch fabric-wide slowdowns)

The relative outlier rules only catch a node that's slow *relative to its peers*;
they miss a uniform regression where everything is equally slow. Pass a nominal
per-node bandwidth to flag that case:

```bash
cinetic analyze <run> --topology topologies/leonardo.json --expected-bw 24
```

The healthy plateau measured here is ~24.5 GB/s (full-duplex busbw), so ~24 is a
reasonable floor anchor; `--expected-frac` (default 0.8) sets the cutoff. The
report then prints `vs nominal: median X% [OK|DEGRADED]` and flags any node (and
the whole run) below the floor. Set `CINETIC_EXPECTED_BW` in the `leonardo`
preset's `env` to apply it automatically without the flag. The report also
surfaces `Total window timeouts` (hard stalls) when the benchmark reports any.

## Before you run — check these

- **Account / QoS**: the `leonardo` preset hardcodes `--account=IscrB_SWING` and
  `--partition=dcgp_usr_prod`, with no QoS (default DCGP QoS). The small node
  counts (2–16) run on those defaults. The large counts add per-config Slurm
  directives via `sbatch_directives` in the JSON — `tournament_N32.json` and
  `tournament_N64.json` set `--qos=dcgp_qos_bprod` and `--cpus-per-task=112`.
  Confirm the account is yours and the QoS allows your node count / walltime.
  NB: `sbatch_directives` (not `system_sbatch`, which is reserved for the
  preset) is the key the engine forwards to the job script.
- **walltime / timeout**: configs use `walltime=00:30:00`, event-loop
  `timeout=1500s`. Raise both for very large node counts.
- **Even node counts only** (tournament constraint with `ppn=1`).
