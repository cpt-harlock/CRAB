# PLAN — Tournament Result Analyzer

A Python tool that turns the **per-node CSV dumps** of `benchmarks/blink/tournament_nb.c`
into per-node / per-round / overall **bandwidth & latency** statistics, annotates every
pairing with **topology distance**, summarizes the **topology mix per round**, flags
**under-performing nodes**, and renders everything both as **text** and as **graphical
plots**.

---

## 1. Inputs

### 1.1 Per-node result files (primary input)
One CSV per rank, written by `write_node_results()` into the experiment data dir
(`data/<system>/<run>/<exp_id>/node_<host>_rank<rank>.csv`).

Current (new) format — header is authoritative, parse **by name not position**:

```
node,rank,peer_node,peer_rank,sample,duration_s
lrdn2866.leonardo.local,0,lrdn2876.leonardo.local,3,0,0.010920228
...
========================================        <- fence between rounds (peer changes)
lrdn2866.leonardo.local,0,lrdn2873.leonardo.local,1,20,0.010...
```

Confirmed against a real 4-node run
(`data/local/2026-06-24_21-43-06-014945/default_ex`): header order exactly as above,
3 rounds × 20 samples per file, 2 `=` fences, hosts `lrdn0271/0448/0451/0843` as FQDNs.

**Per-node files hold only the *last* run.** `write_node_results()` opens with mode
`"w"`, so across the engine's `minruns..maxruns` repetitions each run overwrites the
files. The aggregated/all-runs data lives in `data_app_<id>.csv` / `stdout_app_<id>.log`.
This analyzer therefore characterizes the **final run** — state that in the report.

Robustness requirements (older runs exist with a different column order and **no**
fences):
- Detect columns from the header line; don't assume order.
- Treat any line of `=` as an optional separator to skip.
- Define a **block** (= one match against one peer) canonically by **peer change**,
  so the parser works with or without fences.

### 1.2 Topology file (`topologies/leonardo.json`, etc.)
Loaded via the existing model: `src/cinetic/topology/model.py` →
`Topology.load(path)`. Gives us:
- `Topology.locality(host_a, host_b)` → `Locality.{SAME_SWITCH, SAME_CELL, CROSS_CELL}`
  (or `None` if a host is unknown). This is the **distance** between a pair.
- `Node.cell`, `Node.switches`, `Cell` membership for richer per-round topology stats.

**Hostname normalization (critical):** CSV hosts are FQDNs (`lrdn2866.leonardo.local`)
but the topology keys are short names (`lrdn2866` — verified in `leonardo.json`).
Normalize by stripping the domain suffix (everything after the first `.`) before any
topology lookup. Keep a small `resolve_host()` that tries exact match, then short name,
then logs unresolved hosts.

**Wrong-topology guard:** if fewer than (say) 80% of the run's hosts resolve in the
topology, warn loudly — it almost certainly means the topology file doesn't match the
run's system (e.g. analyzing a Leonardo run with `pitagora.json`). Don't silently emit an
all-"unknown" locality analysis.

### 1.3 Benchmark parameters (needed for bandwidth)
`duration_s` is the wall-time of one measured sample = `measure_granularity` windowed
exchanges. Each exchange moves `window * msg_size` bytes **in each direction**, so the
full-duplex aggregate is `2 * window * msg_size`. Therefore:

```text
bytes_per_sample      = 2 * window * msg_size * measure_granularity
bandwidth_fullduplex  = bytes_per_sample / duration_s      # both directions summed
bandwidth_unidir      = bandwidth_fullduplex / 2           # per-direction
```

**Directionality matters for interpretation.** `bytes/exchange` in the stdout header
(536870912 = `2*64*4194304`) is the **bidirectional aggregate**, so the headline
bandwidth is full-duplex aggregate. Report it labeled as such and also emit the
unidirectional figure (= half), which is what compares to a NIC's per-direction line
rate. Use **decimal GB/s** (`/1e9`) and say so in the report (not GiB/s), to stay
consistent with how HPC NIC rates are quoted.

`window`, `msg_size`, `measure_granularity` are **not** in the node CSVs. Source them in
this priority order:
1. Explicit CLI flags `--msg-size`, `--window`, `--granularity`.
2. **`stdout_app_<id>.log`** in the same exp dir (present when `collect=true`): its
   Tournament header line prints `msg-size`, `window`, and even `bytes/exchange`
   directly — e.g. the real run shows
   `msg-size: 4194304, window: 64, ... bytes/exchange: 536870912`. Prefer parsing
   `bytes/exchange` straight from this line (it already folds in the `×2` full-duplex
   factor); it is multi-run (`=== Run N ===` blocks) but the params are constant, so read
   the first header. (`measure_granularity` is *not* in the header — take it from CLI /
   `config.json` args, default 1.)
3. Parse `config.json` → the tournament app's `args` string (`-msgsize`, `-window`,
   `-grty`) found next to the node files (walk up from the exp dir).
4. Fall back to the **compiled defaults** of `tournament_nb.c`
   (`msg_size=4194304`, `window=64`, `measure_granularity=1`). Keep these as named
   constants with a comment pointing at the C source.

In all cases **print which source was used** so the user can catch a mismatch. Note: when
`collect=false`, `stdout_app_<id>.log` is absent and the master's stdout header never
reaches `slurm_output.log`, so only sources 1/3/4 apply.

### 1.4 Latency definition
This is a windowed bandwidth benchmark, so latency is **derived** (amortized), not an
isolated round-trip. Two series:

- **Per-iteration latency** (primary) = `duration_s / (window * measure_granularity)`.
  The exchange posts `window` outstanding message-pairs per sample (× `granularity`), so
  this is the amortized wall-time per iteration of the window loop.
- **Exchange latency** (secondary) = `duration_s` — time to complete one full windowed
  exchange.

**Honesty caveat (put it in the report header):** because the window is *pipelined* (all
`window` sends/recvs are in flight at once), per-iteration latency is an amortized
throughput-bound figure, **not** a ping-pong half-RTT. At large `msg_size` it tracks
bandwidth (it is essentially `msg_size / unidirectional_bandwidth`). It is only an
**accurate latency when `window == 1`** — then there is no pipelining and
`duration_s / granularity` is the real per-iteration round-trip time. For `window > 1`
treat it as amortized only. When `window != 1`, the report should print this caveat next
to the latency figure (and a true wire latency would need a dedicated `window=1`,
small-`msgsize` run).

---

## 2. Data model (in-memory)

```text
Sample        : (node, rank, peer_node, peer_rank, sample_idx, duration_s)
Match         : one (node -> peer) block = list[Sample] + derived stats
                (this node's *directed* view of one pairing in one round)
Pairing       : the undirected pair {A,B} in a given round; merges A's Match and
                B's Match (both endpoints measure the same exchange). Carries the
                topology Locality for {A,B}.
Round         : the set of Pairings that ran simultaneously (tournament step).
Dataset       : everything parsed from one experiment dir (renamed from "Run" to
                avoid clashing with the engine's repetition "Run N").
```

**Pairing merge rule.** A and B measure the *same* physical exchange (barrier + ack
synced), so their `duration_s` are near-equal. Collapse each Pairing to a **single**
value per sample = mean of the two endpoints' durations (record their abs difference as a
sync-skew diagnostic; warn if large). Per-round and overall **distributions use one value
per Pairing** (no double counting). Per-node stats stay **directed** (each node keeps its
own Matches), which is what makes a slow node show up across all `w_size-1` of its
pairings.

### 2.1 Round alignment across files
The tournament is globally barrier-synchronized: the *k*-th block in every node's file
is round *k*. So:
- Parse each file into ordered blocks; **block index = round index**.
- Sanity check: all files should have the same block count and the pairing implied by
  the blocks must be consistent (A's round-k peer is B ⇒ B's round-k peer is A). Warn on
  mismatch.

**Wrap caveat:** the C ring buffer holds `max_samples` (default 1000). If
`num_rounds * max_iters > max_samples`, early rounds are evicted and files won't start at
round 0. Detect this (block count `< w_size-1`, or first-sample index `> 0`) and:
- Fall back to identifying matches by the **unordered pair set** rather than absolute
  round index, and label rounds as "observed round 0..n" with a warning that early
  rounds were truncated.

---

## 3. Statistics

Use robust stats (median / MAD) as primary, mean/std as secondary, since HPC timing has
heavy right tails. Reuse `numpy`/`scipy` (already available: numpy 2.4, scipy 1.17,
pandas 3.0).

Per **Match** (node→peer): n, median/mean/min/max/std/p95 of duration; same for
bandwidth; timeout/anomaly count (e.g. samples > k×median).

Per **Round**: aggregate bandwidth & latency across all pairings; topology mix (see §4).

Per **Node** (across all its matches): median bandwidth & latency (its headline number),
distribution, and per-locality breakdown (its bandwidth when SAME_SWITCH vs SAME_CELL vs
CROSS_CELL).

**Overall**: global median/mean bandwidth & latency, distribution, totals, and a
bandwidth-vs-locality summary (does crossing cells cost bandwidth?).

---

## 4. Topology analysis per round

For each round, for every pairing classify `locality(A,B)` and tally:
- `n_same_switch` (intra-switch), `n_same_cell` (intra-cell, cross-switch),
  `n_cross_cell` (inter-cell), `n_unknown` (host not in topology).
- Also report which switches/cells were involved (counts), so the user sees the spread.

Per round table row:
```
round | pairings | same_switch | same_cell | cross_cell | unknown | med BW | med lat
```

Overall topology mix = sum across rounds, plus the bandwidth distribution grouped by
locality class (the headline "distance vs performance" result).

---

## 5. Under-performing node detection

Goal: "how many nodes are far from the average/median".

Method (robust, default):
1. Per-node headline metric = median bandwidth across all its matches (latency variant
   too).
2. Compute global median `M` and MAD across nodes.
3. Flag node as **slow** if `bandwidth_node < M - k * 1.4826 * MAD` (default `k=3`), i.e.
   a robust z-score below `-k`. Symmetric option to also flag suspiciously fast.
4. Secondary view: flag nodes below a percentile threshold (e.g. < 10th pct) and nodes
   whose bandwidth is < `frac` × median (default `frac=0.7`).

**Small-N guard (important).** MAD across a handful of nodes is statistically
meaningless (the real run has only 4 nodes), and per-match we have ~20 samples from the
single *final* run. So: when node count is below a threshold (default `< 8`), make the
absolute `frac × median` rule the **primary** flag and demote the robust z-score, and
print a "low-confidence: few nodes / single run" warning. Above the threshold, the
z-score leads.

Report: count of flagged nodes, the list with their value, robust z-score, deviation %,
and their dominant locality (to disentangle "slow node" from "node that happened to draw
cross-cell pairings"). Make `k`/`frac`/percentile/`min-nodes` CLI-tunable.

---

## 6. Outputs

### 6.1 Textual report (stdout + `report.txt`)
Sections: run metadata (params + their source, hosts, topology file) → overall stats →
per-round table (§4) → per-node table sorted by bandwidth → bandwidth-by-locality →
**flagged under-performers** (§5). Use `rich` (already a dep) for tables if a `--rich`
flag is set; plain text otherwise. Optionally emit a machine-readable `summary.json`.

### 6.2 Graphical report (matplotlib → `plots/` dir, PNG; `--show` to display)

**v1 (core):**
1. **Per-node bandwidth bar chart** — sorted, with global median line and flagged nodes
   colored red. (headline "who's slow")
2. **Per-node latency bar chart** — same layout.
3. **Bandwidth-vs-locality box/violin** — distribution grouped by SAME_SWITCH /
   SAME_CELL / CROSS_CELL (the distance-vs-performance plot).
4. **Per-round stacked bar** — locality mix per round (intra-switch/intra-cell/cross),
   with a twin axis line for round median bandwidth.

**Later (deferred):**
5. **Pairwise heatmap** — N×N matrix of median bandwidth (node × peer); reveals bad
   links/quadrants. Cell color = bandwidth; annotate locality with hatching/border.
6. **Per-round bandwidth box plot** — distribution of pairings per round.
7. **Distribution histogram/CDF** — overall bandwidth & latency, flagged region shaded.
8. (Optional, `--topo-graph`) a node-link diagram colored by performance, laid out by
   cell/switch — gate behind a flag since large fabrics are unwieldy.

One multi-panel summary figure (`overview.png`) plus the individual PNGs.

---

## 7. CLI & structure

New script `tournament_analyzer.py` at repo root (sibling of `blink_plotter.py`),
backed by a package `src/cinetic/analysis/` so logic is importable/testable:

```
src/cinetic/analysis/
  __init__.py
  parse.py      # node-CSV -> Sample/Match/Round model (format-tolerant, §1.1/§2)
  params.py     # resolve msg_size/window/granularity (§1.3) from CLI/config/defaults
  metrics.py    # bandwidth/latency math + robust stats (§3)
  topo.py       # hostname normalization + locality lookups, wraps Topology (§1.2/§4)
  outliers.py   # under-performer detection (§5)
  report_text.py# textual/rich + summary.json (§6.1)
  report_plot.py# matplotlib figures (§6.2)
tournament_analyzer.py   # argparse entrypoint wiring the above
```

CLI:
```
python tournament_analyzer.py <run_dir | exp_dir> \
    --topology topologies/leonardo.json \
    [--msg-size N] [--window N] [--granularity N] \
    [--outdir <dir>] [--show] [--rich] [--json] \
    [--slow-k 3.0] [--slow-frac 0.7] [--slow-pct 10] \
    [--units GB/s]
```
- Accepts either a run dir (auto-find the exp subdir(s)) or a specific exp dir.
- If `--topology` omitted, try the run's preset `topology` key / `topologies/` and warn
  if locality analysis is therefore skipped (degrade gracefully — still do BW/lat).
- Default `--outdir` = `<exp_dir>/analysis/`.

---

## 8. Edge cases / robustness
- **No topology / unknown hosts** → still produce BW & latency; mark locality "unknown";
  report unresolved hosts.
- **Old CSV format / no fences** → handled by name-based header parse + peer-change
  blocking (§1.1).
- **Ring-buffer wrap / truncated early rounds** → detect and degrade to pair-set matching
  with a warning (§2.1).
- **Odd world size** (a rank paired with itself) → tournament forbids odd `w_size`, but
  guard against `peer == self` blocks and exclude them from BW stats.
- **Single sample / empty match** → guard stats; report n.
- **Inconsistent pairings** (A says peer B, B says peer C for same round) → warn, keep
  per-node view, skip the merged Pairing.
- **Param mismatch** → since BW scales linearly with assumed `bytes_per_sample`, always
  print the param source; consider a `--bw-relative` mode that reports BW normalized to
  the run median so conclusions are param-independent.

---

## 9. Implementation milestones
1. `parse.py` + `params.py` — load one exp dir into the model; develop against the real
   run `data/local/2026-06-24_21-43-06-014945/default_ex` (new format, 4 nodes, 3 rounds,
   `stdout_app_0.log` present). Print a basic per-match table. (No topology yet.)
2. `topo.py` — hostname normalization + per-pairing locality; per-round topology mix
   table. Validate against `topologies/leonardo.json`.
3. `metrics.py` — bandwidth/latency + robust stats; per-node/per-round/overall.
4. `outliers.py` — flagging; tune defaults on real data.
5. `report_text.py` — full textual report + `summary.json`.
6. `report_plot.py` — the figures in §6.2.
7. `tournament_analyzer.py` — wire CLI, graceful degradation, docs in `CLAUDE.md`.
8. Smoke-test end-to-end on a fresh run produced by the rebuilt binary (new CSV format
   with fences) on real Leonardo nodes so locality is meaningful.

**MVP cut:** milestones 1–5 + the four v1 figures (§6.2) deliver a usable tool; the
deferred figures and `--topo-graph` (milestone 6's "later" items) come after.

---

## 10. Open questions (assumptions if unanswered)
- **Latency semantics**: *decided* — primary latency = per-iteration =
  `duration_s / (window * granularity)`, reported as an amortized (pipelined) figure with
  the §1.4 caveat; exchange latency (`duration_s`) kept as secondary.
- **"Distance" granularity**: assume the 3-level `Locality` enum is sufficient; if a
  finer hop-count is wanted, it would need topology graph shortest-path (not currently in
  the model) — flag as a possible extension.
- **Multiple experiments / runs in one dir**: assume analyze each exp dir independently;
  a `--compare` mode across runs is a future extension.
