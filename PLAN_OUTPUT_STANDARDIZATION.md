# PLAN — Standardized Per-Node Experiment Output

Make every benchmark emit results in **one self-describing per-node format**,
generalized from `benchmarks/blink/tournament_nb.c`'s
`node_<host>_rank<r>.csv`, so a single analyzer path handles point-to-point
*and* collective benchmarks (allgather, allreduce, alltoall, …) and reports
**bandwidth + latency in a topology-aware way** for all of them.

Companion to `PLAN_RESULT_ANALYZER.md` (the v1 tournament analyzer) and
`PLAN_ANALYSIS_REWORK.md` (the analysis extension): this plan standardizes the
*producer* side so the *consumer* side can be uniform and simple. Status keys:
☐ todo, ◐ partial (exists), ✔ done.

---

## 0. Goal & the core problem

The tournament per-node CSV is good because it is **per-node, per-sample, and
peer-attributed**: each row is "node N, sample i, talked to peer P, took
duration d." That lets the analyzer compute per-node bandwidth/latency and
bucket it by the **topology distance** of the (N, P) pair.

Collectives break the per-peer assumption: in an allreduce/allgather/alltoall a
rank communicates with a **set** of peers (often the whole communicator), not a
single one. So "peer_node / topology distance of the pair" is undefined. The
challenge is to keep the per-node granularity and a topology-aware view while
generalizing "one peer" → "a peer set."

**Two facts make this tractable:**
1. Every benchmark already times its own operation per iteration into a
   `durations[]` ring buffer (`common.h`); only the *dump* differs. So per-node,
   per-sample timing is universal — we just need a shared writer.
2. For bandwidth/latency we don't need the analyzer to know each op's algorithm
   if the **emitter** writes the bandwidth/latency *bases* (bytes moved, ops per
   sample) — the emitter knows the algorithm; the analyzer stays generic.

---

## 1. The unified per-node record

One CSV per rank, `node_<host>_rank<r>.csv`, parsed **by header name** (the
current parser already does this, so old files keep working). Columns:

```
node,rank,op,comm,sample,phase,peer_node,peer_rank,bytes,ops,duration_s
```

| column        | meaning                                                                 |
|---------------|-------------------------------------------------------------------------|
| `node`,`rank` | this rank's host + MPI rank (as today)                                   |
| `op`          | operation tag: `pairwise_fd`, `allreduce`, `allgather`, `alltoall`, …    |
| `comm`        | communicator id (0 = COMM_WORLD; >0 = sub-comm). Links to the manifest §2|
| `sample`      | chronological sample index (LRU-ring index, as today)                    |
| `phase`       | sub-step within the op: tournament *round*, or ring *step*; `-1` if n/a  |
| `peer_node`,`peer_rank` | the single counterparty for **pairwise** rows; **empty / `-1`** for collective rows (peer set = the comm, see §2/§4) |
| `bytes`       | **bandwidth basis**: bytes moved by *this rank* for this sample (emitter computes per algorithm) |
| `ops`         | **latency basis**: number of latency-units folded into this sample       |
| `duration_s`  | measured wall-time of the sample                                         |

Then, uniformly, the analyzer computes:
```
bandwidth = bytes / duration_s          # GB/s, decimal
latency   = duration_s / ops            # per-unit time
```
No more reverse-engineering msg_size/window/granularity from stdout/config — the
two **basis columns** make every benchmark's bandwidth and latency directly
comparable. This is the central simplification.

**The tournament is the degenerate case.** A pairwise row has one peer, so it
keeps `peer_node/peer_rank`; its `bytes = 2*window*msg_size*granularity`,
`ops = window*granularity`, `phase = round`. The `=`-fence between rounds is
replaced by the explicit `phase` column (the parser may still skip stray fence
lines for back-compat).

### 1.1 Bandwidth basis per op (busbw convention)
The emitter fills `bytes` using the standard **bus-bandwidth** convention
(per NCCL/OSU), so numbers reflect link pressure, not just user payload. `N` =
comm size, `S` = msg_size (the per-op size as each benchmark already defines it):

| op            | `bytes` (per rank, per sample)        | notes                          |
|---------------|---------------------------------------|--------------------------------|
| `pairwise_fd` | `2 * window * S * granularity`         | full-duplex aggregate (today)  |
| `alltoall`    | `2 * (N-1) * S`                        | sends to & recvs from N-1 peers|
| `allgather`   | `2 * (N-1)/N * (N*S_chunk)` = `2*(N-1)*S_chunk` | ring; `S_chunk` = per-rank contribution |
| `allreduce`   | `2 * (N-1)/N * S`                      | ring/r-d standard busbw        |
| `broadcast`/`reduce` | `S` (root-relative)            | document the asymmetry         |

These formulas live **once** in the shared C writer (§3), keyed by `op`, with a
comment citing the convention. The analyzer never re-derives them.

---

## 2. Communicator manifest (the "peer set")

A collective row's counterparty is its communicator. To make topology analysis
possible we emit, once per run, a **manifest** mapping each comm to its members:

`comm_manifest.csv` in the experiment dir:
```
comm,rank,node
0,0,lrdn0271
0,1,lrdn0843
...
1,0,lrdn0271      # a sub-comm, e.g. one switch's worth of ranks
1,1,lrdn0451
```

Written collectively (every rank already Allgathers hostnames in
`write_node_results`; extend that to also dump membership for each comm it
belongs to; rank 0 of each comm writes its block, or rank 0 of WORLD writes all
via a gather). For a plain COMM_WORLD run this is a single block = all nodes.

The manifest is what lets the analyzer turn "peer set" into topology structure
(§4) without the rows themselves carrying N peers each.

---

## 3. Shared C results library

Factor the per-node dump out of `tournament_nb.c` into a reusable unit so every
benchmark emits the identical format with ~5 lines of glue.

`benchmarks/blink/results.h` (+ `results.c`):
```c
typedef struct { /* op, comm, ring buffers for duration/peer/phase/bytes/ops */ } cin_results;

void cin_results_init(cin_results*, const char *op, MPI_Comm comm,
                      int max_samples);
/* peer_rank < 0  => collective sample (peer set = comm) */
void cin_results_record(cin_results*, double duration_s, int peer_rank,
                        int phase, double bytes, double ops);
void cin_results_write(cin_results*);   /* hostname Allgather + LRU reconstruct
                                           + write node_<host>_rank<r>.csv +
                                           contribute to comm_manifest.csv */
```

- Moves the LRU-wrap reconstruction, `MPI_Get_processor_name` Allgather,
  `CINETIC_NODE_RESULTS_DIR` resolution, and CSV writing (currently all inside
  `tournament_nb.c:write_node_results`) into one place.
- `tournament_nb.c` becomes a thin caller: `cin_results_record(&r, dur,
  partner_rank, round, 2.0*window*msg*gran, (double)window*gran)`.
- Each collective adds the same three calls around its existing
  `durations[]` write. Keep `write_results()` (stdout aggregate) for
  back-compat, or have the analyzer stop needing it.

Milestone ordering keeps risk low: build the library by extracting the proven
tournament code verbatim, prove byte-identical output for tournament, *then*
wire collectives.

---

## 4. Topology analysis for collectives (the hard part)

Per-peer locality (`Topology.locality(node, peer)`) is undefined for a peer set.
Three complementary views, in increasing richness:

### 4.1 Communicator-span class (always available, from the manifest)
Classify each comm by how its members spread over the fabric:
- `span = SAME_SWITCH` if all members share one leaf switch,
- `SAME_CELL` if within one cell (≤1 spine hop),
- `CROSS_CELL` otherwise; plus counts `n_switches`, `n_cells`, and the
  member-pair locality histogram (how many member pairs are same_switch / …).

Then bucket per-node collective bandwidth/latency **by comm span** — the direct
analog of the tournament's "bandwidth by topology distance." Example readout:
"allreduce over a single-switch comm vs over a cross-cell comm."

**Caveat (call it out in the report):** with a single COMM_WORLD run there is
only *one* span, so this axis is a single bucket. It becomes informative only
when the experiment runs the collective over **sub-comms of differing span**
(e.g., allreduce within each switch, within each cell, across cells). That is a
natural, recommended experiment design — and the manifest (§2) captures exactly
which comm had which span. Consider a driver/benchmark mode that builds such
sub-comms (an `MPI_Comm_split` sweep) so the locality axis is populated.

### 4.2 Per-node straggler view (always available)
A collective is gated by its slowest participant. Per-node duration already
reveals stragglers; cross-reference with each node's topology position (its
switch/cell, and whether it is the lone cross-cell member of the comm). Question
answered: "is the straggler consistently the topologically-distant node?" This
reuses the tournament analyzer's under-performer detection (`outliers.py`)
unchanged — it only needs per-node values, which we now have for collectives.

### 4.3 Algorithm-aware per-peer (opportunistic, Tier-3)
Benchmarks that implement the pattern **manually** already know their neighbors
per phase — e.g. `agtr_comm_only.cpp`'s ring allgather sends to a fixed
left/right neighbor each step. Those can call `cin_results_record` with a real
`peer_rank` and `phase`, producing fully tournament-compatible rows and getting
the exact per-pair locality analysis for free. Opaque MPI collectives
(`MPI_Iallreduce`, `MPI_Ialltoall`) cannot — they only get 4.1 + 4.2.

**Decision (recommended):** do **4.1 + 4.2 for every benchmark** (cheap, from
per-node timing + manifest), and **4.3 wherever the algorithm is already
explicit** (ring allgather, ring/incast/o2o patterns). Do *not* rewrite opaque
MPI collectives into manual algorithms just for peer attribution — that changes
what is being measured. Manually-implemented variants are the place to get the
richest topology view.

---

## 5. Analyzer changes (consumer side)

Mostly additive; the math core (`metrics.py`, `outliers.py`) is reused.

- **`parse.py`**: read the new columns by name; `op`/`comm`/`bytes`/`ops`/`phase`
  optional. A row with `peer_rank < 0`/empty is a **collective sample** tied to
  its `comm`. Load `comm_manifest.csv` into the dataset.
- **back-compat**: legacy tournament files (no `op/comm/bytes/ops/phase`) →
  default `op=pairwise_fd`, `comm=0`, `phase` from peer-change/fence, and
  `bytes/ops` from the existing params layer (`params.py`) — current behavior,
  nothing breaks.
- **`metrics.py`**: bandwidth `= bytes/duration`, latency `= duration/ops` when
  the basis columns are present (uniform across benchmarks); fall back to the
  params formula only for legacy files.
- **`topo.py`**: add `comm_span(comm)` from the manifest (§4.1) and the member-
  pair locality histogram.
- **new buckets**: "by comm span" (collective analog of "by locality"); reuse
  per-node + straggler views (§4.2) as-is.
- **report/plots**: where the row is pairwise → existing per-peer/locality
  output; where collective → per-comm-span buckets + straggler topology view.
  One report, two code paths selected by `op`/peer presence.

---

## 6. Milestones

1. **[DONE]** **Schema + library**: write `results.h` (header-only) by extracting
   `tournament_nb.c`'s dumper; add `op/comm/bytes/ops/phase` columns; emit
   `comm_manifest.csv`. Re-point `tournament_nb.c` at it; verified
   equivalent analysis on an existing run.
2. **[DONE]** **One collective, Tier-1/2**: wired `ardc_nb` (allreduce) and
   `a2a_nb` (alltoall) to record per-node samples with `bytes/ops` + manifest.
3. **[DONE]** **Analyzer**: generalized `parse`/`metrics`/`topo` (§5); added the
   comm-span bucket and the "by comm span" report/plots; legacy path green.
4. **[DONE]** **Sub-comm span sweep**: `-splitsize N` (`MPI_Comm_split`) mode on
   the collectives populates the locality axis; race-free manifest records each
   comm's members.
5. **[DONE]** **Tier-3 opportunistic**: `agtr_comm_only`'s ring records per-peer
   (ring successor) rows → directed per-hop locality; analyzer "directed" kind.
6. **[DONE]** **Docs**: updated `CLAUDE.md` (output format + "writing a benchmark
   that emits standardized results") and cross-linked the analyzer plans.

**MVP**: milestones 1–3 — every benchmark emits per-node bandwidth/latency the
analyzer can read uniformly, with per-node + straggler topology views. Span
sweep (4) and Tier-3 (5) deepen the topology story.

---

## 7. Risks / decisions

- **busbw vs algbw / payload**: pick **busbw** and print the convention in the
  report so cross-op comparisons are honest; record raw `bytes` so a different
  convention can be recomputed downstream.
- **Single-comm runs give a trivial locality axis** for collectives (§4.1) —
  surface this clearly and push the sub-comm sweep (milestone 4) as the way to
  make it meaningful.
- **Opaque collectives have no peers** — accept Tier-1/2 for them; don't fake
  per-peer data. Only manually-implemented patterns get Tier-3.
- **Ring-buffer wrap** (already seen at 128 nodes): the shared writer must keep
  the LRU reconstruction; document `-maxsamples` sizing (`rounds*iters` for
  pairwise, `iters` for collectives) in the writer's header comment.
- **Don't break existing tournament files / reports** — the schema is a strict
  superset and the parser is name-based; verify in milestone 1.

---

## 8. Open questions (assumptions if unanswered)

- **Where to attribute collective bandwidth**: per-rank busbw (recommended,
  uniform with per-node view) vs a single comm-level number. Assume per-rank.
- **Latency meaning for collectives**: full-op completion time per rank
  (`ops=granularity`) — assume yes; note it is gated by the slowest rank.
- **Sub-comm sweep ownership**: a new benchmark binary vs a driver that runs the
  existing collective over `MPI_Comm_split` groups. Assume the latter is cheaper
  and reuses all existing benchmarks; confirm.
- **Keep `write_results()` stdout CSV?**: assume keep during migration (other
  tooling may read it), drop once the analyzer is fully on per-node files.
