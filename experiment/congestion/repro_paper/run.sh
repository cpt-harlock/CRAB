#!/bin/bash
# Reproduce the Leonardo AllGather-victim congestion experiments from
#   "Characterizing the Impact of Congestion in Modern HPC Interconnects"
#   (Piarulli et al.), Figure 5 (center column).
#
# Two experiments, one per aggressor (AlltoAll, Incast). For each, a 2D grid of
#   node count  x  victim AllGather vector size,
# matching the paper: ring AllGather victim, 1000 iterations (100 discarded),
# 50:50 interleaved victim/aggressor, aggressor in an endless loop. Metric is the
# ratio uncongested/congested victim runtime (computed by analyze.sh).
#
# Paper system = Leonardo *Booster* (HDR IB, Dragonfly+) — which is the site
# default in experiment/lib/launch.sh (partition/QOS/reservation + NO_AUTO_QOS).
# All knobs (PARTITION/ACCOUNT/QOS/GRES/RESERVATION/EXTRA_SBATCH/NO_AUTO_QOS/
# CHAIN/PRESET) override from the environment — e.g. the 128/256-node tier needs
#   QOS=boost_qos_bprod GRES=gpu:4 EXTRA_SBATCH="--cpus-per-task=32"
# and CHAIN=1 serializes the grid (no cross-job false congestion).
set -uo pipefail

# --- axes (paper: 16..256 nodes, vectors 8 B .. 16 MiB x8) -------------------
NODE_COUNTS="${NODE_COUNTS:-16 32 64 128 256}"
VICTIM_MSG_SIZES="${VICTIM_MSG_SIZES:-8 64 512 4096 32768 262144 2097152 16777216}"
AGGRESSORS="${AGGRESSORS:-alltoall incast}"
ITERS="${ITERS:-1000}"; WARMUP="${WARMUP:-100}"
WALLTIME="${WALLTIME:-00:30:00}"

# --- REPS: resubmit each cell N times. Every job gets a fresh Slurm allocation,
#     so reps land on different node sets (different topology placement) — that's
#     the replicate-level variance the in-run iterations can't sample. analyze.sh
#     aggregates all reps of a cell into mean +/- std. Combine with CHAIN=1 so the
#     reps still run one-at-a-time (no cross-job false congestion).
REPS="${REPS:-1}"

# --- aggressor message size: NOT stated in the paper (fixed background noise).
#     ASSUMPTION, override via AGGR_MSG. ~1 MiB maximised contention in our own
#     dose-response on DCGP. Special value AGGR_MSG=match ties the aggressor's
#     message size to the victim's vector size *per cell* (the hypothesis that the
#     paper scaled the aggressor with the y-axis) — each cell then lands in its own
#     am<VM> dir, so a matched sweep does not clobber the fixed-size column.
AGGR_MSG="${AGGR_MSG:-1048576}"

# --- repro-specific default (env still overrides). The Booster partition/QOS/
#     reservation + NO_AUTO_QOS come from experiment/lib/launch.sh's site defaults.
GRES="${GRES:-tmpfs:0}"

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1
source experiment/lib/launch.sh
GEN="experiment/congestion/repro_paper/generated"; mkdir -p "$GEN"

for AGG in $AGGRESSORS; do
  for N in $NODE_COUNTS; do
    for VM in $VICTIM_MSG_SIZES; do
      if [ "$AGGR_MSG" = "match" ]; then amsg="$VM"; else amsg="$AGGR_MSG"; fi
      for REP in $(seq 1 "$REPS"); do
        cfg="$GEN/repro_agtr_${AGG}_n${N}_vm${VM}_am${amsg}_r${REP}.json"
        launch_dep_args
        if python experiment/congestion/gen_config.py \
             --victim allgather --aggressor "$AGG" --nodes "$N" \
             --victim-msgsize "$VM" --aggr-msgsize "$amsg" \
             --iters "$ITERS" --warmup "$WARMUP" --walltime "$WALLTIME" \
             "${LAUNCH_GEN_ARGS[@]}" "${LAUNCH_DEP_ARGS[@]}" -o "$cfg" >/dev/null; then
          launch_submit "$cfg" "allgather vs $AGG | ${N} nodes | victim vec ${VM} B | aggr ${amsg} B | rep ${REP}/${REPS}"
        fi
      done
    done
  done
done

launch_footer
echo "  axes: nodes={$NODE_COUNTS}  victim-vec={$VICTIM_MSG_SIZES}  aggr-msg=$AGGR_MSG  reps=$REPS"
echo "Analyze with: experiment/congestion/repro_paper/analyze.sh"
echo
echo "NB: full grid = 2x5x8 = 80 cells up to 256 Booster nodes, x REPS jobs each."
echo "    Start with a subset, e.g."
echo "    NODE_COUNTS='16 32' VICTIM_MSG_SIZES='4096 2097152' REPS=5 CHAIN=1 $0"
