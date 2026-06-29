# Congestion experiment (Leonardo DCGP)

Measures how much a co-running **aggressor** degrades a **victim** benchmark's
bandwidth when they share the same fabric — the network-congestion use case
CINETIC exists for.

## Design

- **Victim**: `tournament_nb` (all-pairs full-duplex bandwidth), the benchmark we
  validated in the saturation sweep (~24.5 GB/s healthy plateau). Its drop under
  load is directly interpretable per node and per topology distance.
- **Aggressor**: `a2a_nb -endl` (endless alltoall) — the classic bisection
  stressor; `end:"f"` so the engine kills it the moment the victim finishes.
- **Placement**: `allocationmode=p`, `partitionsplit=50:50`, `partitionlayout=i`
  (interleaved). Nodes are dealt round-robin to partition 0 (victim) and
  partition 1 (aggressor), so victim and aggressor sit on **adjacent hosts /
  shared cells** and contend for the same leaf+spine links.
- **Baseline vs loaded in one job**: the config has two experiments — `baseline`
  (victim only; partition-1 nodes idle) and `loaded` (victim + aggressor). They
  run sequentially on the same allocation, so the victim runs on the **same 8
  nodes** in both phases → a clean per-node congestion diff.

Configs:
- `congestion_a2a_n16.json`: 16 nodes → 8 victim + 8 aggressor. Default DCGP QOS.
  **Note:** at 16 nodes everything lands on a single *non-blocking* leaf switch,
  so victim and aggressor (on separate NICs) have no oversubscribed link to
  contend for — this run measures ~0% congestion. It's the negative control.
- `congestion_a2a_n64.json`: 64 nodes → 32 victim + 32 aggressor, interleaved so
  both span multiple **cells**. Now the victim's cross-cell traffic and the
  aggressor's alltoall share **spine links** — the configuration that can
  actually show fabric congestion. Heavier aggressor (`-msgsize 2097152`) to
  maximise bisection pressure. Needs `--qos=dcgp_qos_bprod` (a big-production QOS
  with a node-count minimum; it rejects small jobs, hence n16 omits it).

(8/16/32 victim counts are all even, which tournament requires.)

## Run

```bash
# 0. (on Leonardo) build the benchmarks under the preset's modules
module purge && module load openmpi
( cd benchmarks/blink && make )

# 1. submit (one job, both experiments)
experiment/congestion/run.sh
# or a specific config:
experiment/congestion/run.sh experiment/congestion/configs/congestion_a2a_n16.json

# 2. after it finishes
experiment/congestion/analyze.sh
```

## What to read

The analyzer auto-detects the `baseline` vs `loaded` victim and writes
`congestion.{txt,json,png}` under the run's experiment analysis dir:

- **overall** bandwidth-drop% / latency-increase% (victim, loaded vs baseline);
- **per topology label** (same_switch / same_cell / cross_cell) — shows whether
  contention bites hardest on spine-crossing (cross_cell) traffic;
- **per node**, worst-hit first — which victim nodes the aggressor hurt most;
- a baseline-vs-loaded overlay plot.

Single-run point estimate (final-run-only) is flagged in the report.

Add `--blame --expected-bw 24.5` to localize *where* the slowdown concentrates:
on the loaded run it points at the contended spine switch/links (a `loaded`
warning is printed, since blame then localizes congestion rather than a fault).

## Knobs to vary next

- **Aggressor intensity**: `-msgsize` on app 1 (bigger alltoall messages = more
  bisection pressure).
- **Placement**: `partitionlayout=l` (separate, contiguous partitions) vs `i`
  (interleaved) to contrast shared-cell vs separate-cell contention.
- **Scale**: copy the config to other even node counts (`numnodes`, keep 50:50).
- **Split**: `partitionsplit` to change the victim:aggressor ratio.
