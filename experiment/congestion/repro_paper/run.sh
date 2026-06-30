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
# Paper system = Leonardo *Booster* (HDR IB, Dragonfly+), so this runner DEFAULTS
# the shared scheduler knobs to Booster (boost_usr_prod, no auto DCGP QOS) before
# sourcing experiment/lib/launch.sh. All those knobs
# (PARTITION/ACCOUNT/QOS/GRES/RESERVATION/EXTRA_SBATCH/NO_AUTO_QOS/CHAIN/PRESET)
# still override from the environment — e.g. the 128/256-node tier needs
#   QOS=boost_qos_bprod GRES=gpu:4 EXTRA_SBATCH="--cpus-per-task=32"
# and CHAIN=1 serializes the grid (no cross-job false congestion).
set -uo pipefail

# --- axes (paper: 16..256 nodes, vectors 8 B .. 16 MiB x8) -------------------
NODE_COUNTS="${NODE_COUNTS:-16 32 64 128 256}"
VICTIM_MSG_SIZES="${VICTIM_MSG_SIZES:-8 64 512 4096 32768 262144 2097152 16777216}"
AGGRESSORS="${AGGRESSORS:-alltoall incast}"
ITERS="${ITERS:-1000}"; WARMUP="${WARMUP:-100}"
WALLTIME="${WALLTIME:-00:30:00}"

# --- aggressor message size: NOT stated in the paper (fixed background noise).
#     ASSUMPTION, override via AGGR_MSG. ~1 MiB maximised contention in our own
#     dose-response on DCGP.
AGGR_MSG="${AGGR_MSG:-1048576}"

# --- Booster defaults for the shared scheduler knobs (env still overrides) ----
# ACCOUNT/QOS default empty (ISCRA expired) -> default account + default QOS.
PARTITION="${PARTITION:-boost_usr_prod}"
GRES="${GRES:-tmpfs:0}"
NO_AUTO_QOS="${NO_AUTO_QOS:-1}"   # Booster: don't auto-add the DCGP big-QOS

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"
source experiment/lib/launch.sh
GEN="experiment/congestion/repro_paper/generated"; mkdir -p "$GEN"

for AGG in $AGGRESSORS; do
  for N in $NODE_COUNTS; do
    for VM in $VICTIM_MSG_SIZES; do
      cfg="$GEN/repro_agtr_${AGG}_n${N}_vm${VM}.json"
      launch_dep_args
      if python experiment/congestion/gen_config.py \
           --victim allgather --aggressor "$AGG" --nodes "$N" \
           --victim-msgsize "$VM" --aggr-msgsize "$AGGR_MSG" \
           --iters "$ITERS" --warmup "$WARMUP" --walltime "$WALLTIME" \
           "${LAUNCH_GEN_ARGS[@]}" "${LAUNCH_DEP_ARGS[@]}" -o "$cfg" >/dev/null; then
        launch_submit "$cfg" "allgather vs $AGG | ${N} nodes | victim vec ${VM} B"
      fi
    done
  done
done

launch_footer
echo "  axes: nodes={$NODE_COUNTS}  victim-vec={$VICTIM_MSG_SIZES}  aggr-msg=$AGGR_MSG"
echo "Analyze with: experiment/congestion/repro_paper/analyze.sh"
echo
echo "NB: full grid = 2x5x8 = 80 jobs up to 256 Booster nodes. Start with a subset,"
echo "    e.g.  NODE_COUNTS='16 32' VICTIM_MSG_SIZES='4096 2097152' $0"
