# Repro: AllGather victim under AllToAll / Incast congestion (Leonardo)

Reproduces the Leonardo experiments of **"Characterizing the Impact of Congestion
in Modern HPC Interconnects"** (Piarulli, Faltelli, Pleiter, Sivalingam, … De
Sensi), specifically **Figure 5 (center column)** — steady congestion, ring
**AllGather victim** under an **AllToAll** aggressor and (separately) an
**Incast** aggressor.

## Mapping paper → this harness

| Paper | Here |
|---|---|
| victim = custom ring AllGather (comm-only) | `agtr_comm_only` (`--victim allgather`) |
| aggressor = AllToAll \| Incast (endless) | `a2a_nb` \| `inc_nb` (`-endl`, `end="f"`) |
| 50:50 victim/aggressor, **interleaved** node assignment | `allocationmode=p, partitionsplit=50:50, partitionlayout=i` |
| victim runs 1000 iters, discard first 100, mean of rest | `-iter 1000 -warmup 100` |
| baseline (uncongested) then loaded (congested) | `baseline` + `loaded` experiments in one job |
| x-axis = node count (16…256, half each role) | `NODE_COUNTS="16 32 64 128 256"` |
| y-axis = victim AllGather vector size (8 B…16 MiB ×8) | `VICTIM_MSG_SIZES="8 … 16777216"` |
| cell value = **uncongested/congested runtime ratio** (>1 better) | `base_lat_s/loaded_lat_s` from `congestion.json` |
| system = Leonardo **Booster** (HDR IB, Dragonfly+) | `--partition=boost_usr_prod` (overrides the DCGP preset) |

## Two assumptions (not pinned by the paper)

- **Aggressor message size** — the paper sweeps the *victim* vector size and runs
  the aggressor as fixed background noise without stating its size. Default
  `AGGR_MSG=1048576` (1 MiB, which maximised contention in our own DCGP
  dose-response). Override to taste.
- **Booster account / QOS** — site-specific. Defaults: `PARTITION=boost_usr_prod`,
  `GRES=tmpfs:0`, **no account and no QOS** (the ISCRA allocation expired, so the
  job uses the user's default account / default QOS). Set `ACCOUNT=…` / `QOS=…`
  to add them (large allocations may need a production QOS).

## Run

```bash
# 0. (on Leonardo) build the benchmarks under the preset's modules
module purge && module load openmpi
( cd benchmarks/blink && make )

# 1. submit both experiments (allgather vs alltoall, allgather vs incast)
experiment/congestion/repro_paper/run.sh
#    a subset first (recommended — the full grid is 2×5×8 = 80 jobs to 256 nodes):
NODE_COUNTS="16 32" VICTIM_MSG_SIZES="4096 2097152" \
  experiment/congestion/repro_paper/run.sh
#    one aggressor only:
AGGRESSORS="incast" experiment/congestion/repro_paper/run.sh

# 2. after the jobs finish: per-run diffs + Fig-5 heatmaps
experiment/congestion/repro_paper/analyze.sh
```

## Output

- Per node count, a `compare-congestion` dose-response across victim vector sizes
  under `data/leonardo/_sweep_analysis/repro_paper/congestion_agtr_<a2a|inc>/n<N>/`.
- The **Figure-5 heatmap** per aggressor (ratio uncongested/congested, rows =
  victim vector size, cols = node count):
  `data/leonardo/_sweep_analysis/repro_paper/congestion_agtr_<a2a|inc>_heatmap.csv`.

Per the paper's finding, expect Leonardo to stay near baseline (~0.95–1.05) under
the **AllToAll** aggressor (intermediate-switch contention the Dragonfly+ deflects),
but to **collapse toward ~0.2 at 32–64 nodes under Incast** (edge-localized
congestion at the receiver's leaf that routing can't relieve).
