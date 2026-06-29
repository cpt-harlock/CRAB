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
# Paper system = Leonardo *Booster* (HDR IB, Dragonfly+), so we override the
# preset's DCGP partition to boost_usr_prod via --sbatch.
set -euo pipefail

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

# --- Leonardo Booster scheduler directives (override the DCGP preset) ---------
# ACCOUNT/QOS default to empty (the ISCRA allocation expired) -> the job uses the
# user's default account and the default QOS. Set ACCOUNT=/QOS= to add them.
PARTITION="${PARTITION:-boost_usr_prod}"
ACCOUNT="${ACCOUNT:-}"
GRES="${GRES:-tmpfs:0}"
QOS="${QOS:-}"
PRESET="leonardo"

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"
GEN="experiment/congestion/repro_paper/generated"; mkdir -p "$GEN"

sbatch_args=(--no-auto-qos --sbatch="--partition=$PARTITION")
[ -n "$GRES" ]    && sbatch_args+=(--sbatch="--gres=$GRES")
[ -n "$ACCOUNT" ] && sbatch_args+=(--sbatch="--account=$ACCOUNT")
[ -n "$QOS" ]     && sbatch_args+=(--sbatch="--qos=$QOS")

n=0
for AGG in $AGGRESSORS; do
  for N in $NODE_COUNTS; do
    for VM in $VICTIM_MSG_SIZES; do
      cfg="$GEN/repro_agtr_${AGG}_n${N}_vm${VM}.json"
      python experiment/congestion/gen_config.py \
        --victim allgather --aggressor "$AGG" --nodes "$N" \
        --victim-msgsize "$VM" --aggr-msgsize "$AGGR_MSG" \
        --iters "$ITERS" --warmup "$WARMUP" --walltime "$WALLTIME" \
        "${sbatch_args[@]}" -o "$cfg" >/dev/null
      echo "=== submit: allgather vs $AGG | ${N} nodes | victim vec ${VM} B ==="
      cinetic run -p "$PRESET" -c "$cfg"
      n=$((n + 1))
    done
  done
done

echo
echo "Submitted $n job(s): allgather victim vs {$AGGRESSORS}"
echo "  nodes={$NODE_COUNTS}  victim-vec={$VICTIM_MSG_SIZES}  aggr-msg=$AGGR_MSG  on $PARTITION"
echo "Analyze with: experiment/congestion/repro_paper/analyze.sh"
echo
echo "NB: full grid = ${n} jobs up to 256 Booster nodes; confirm account/QOS and"
echo "    that the aggressor size (AGGR_MSG=$AGGR_MSG) matches your intent. Start"
echo "    with a subset, e.g.  NODE_COUNTS='16 32' VICTIM_MSG_SIZES='4096 2097152' $0"
