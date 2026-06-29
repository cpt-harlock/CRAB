# Tournament bandwidth saturation sweep (Leonardo DCGP)

Runs `benchmarks/blink/tournament_nb` across node counts with a message/window
size that saturates the link, to measure per-node pairwise bandwidth (and its
topology breakdown) as the job scales.

## What it does

- One `cinetic run` per node count (a node sweep can't share a Slurm
  allocation), preset `leonardo` (slurm backend, `dcgp_usr_prod`,
  `--account=IscrB_SWING`).
- `tournament_nb -msgsize 4194304 -window 64` → 512 MB per full-duplex exchange,
  which saturates the rail when the fabric is healthy.
- `ppn=1` so each rank owns its node's link (per-node bandwidth). Node counts are
  **even** — the tournament requires an even rank count.
- `-maxsamples 4000` keeps the per-node LRU ring from wrapping ((N−1)·iters).

Node counts: `2 4 8 16 32 64` (edit `NODE_COUNTS` in the scripts to change).

## Run

```bash
# 0. (on Leonardo) build the benchmark under the SAME modules the preset loads,
#    so the binary matches the runtime MPI:
module purge && module load openmpi
( cd benchmarks/blink && make )

# 1. submit the sweep (one Slurm job per node count)
experiment/saturation_sweep/run_sweep.sh

# 2. after the jobs finish, analyze + compare (bandwidth vs node count)
experiment/saturation_sweep/analyze_sweep.sh
```

Results land under `data/leonardo/tournament_sat_n<N>_<timestamp>/`. The
comparison (overall/by-locality bandwidth vs node count, with a trend) is written
to the first run's `analysis/comparison.{txt,json,png}`.

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
