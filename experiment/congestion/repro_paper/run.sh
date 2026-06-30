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
RESERVATION="${RESERVATION:-}"   # e.g. maint_3006_boost to run inside a maintenance window
EXTRA_SBATCH="${EXTRA_SBATCH:-}" # space-separated extra #SBATCH directives, e.g.
                                 # "--cpus-per-task=32" (the 128/256-node tier needs it)
PRESET="leonardo"

# --- CHAIN=1: serialize the whole grid so no two jobs run at once (avoids
#     cross-job "false congestion"). Each job depends on the previous one via
#     --dependency=afterany:<prev> (fires when prev terminates in ANY state, so
#     one failure won't wedge the rest). Submission order = the loop order below.
CHAIN="${CHAIN:-0}"

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"
GEN="experiment/congestion/repro_paper/generated"; mkdir -p "$GEN"

sbatch_args=(--no-auto-qos --sbatch="--partition=$PARTITION")
[ -n "$GRES" ]        && sbatch_args+=(--sbatch="--gres=$GRES")
[ -n "$ACCOUNT" ]     && sbatch_args+=(--sbatch="--account=$ACCOUNT")
[ -n "$QOS" ]         && sbatch_args+=(--sbatch="--qos=$QOS")
[ -n "$RESERVATION" ] && sbatch_args+=(--sbatch="--reservation=$RESERVATION")
for d in $EXTRA_SBATCH; do sbatch_args+=(--sbatch="$d"); done

n=0
prev=""   # last submitted job id, for the CHAIN dependency
for AGG in $AGGRESSORS; do
  for N in $NODE_COUNTS; do
    for VM in $VICTIM_MSG_SIZES; do
      cfg="$GEN/repro_agtr_${AGG}_n${N}_vm${VM}.json"
      dep_args=()
      [ "$CHAIN" = 1 ] && [ -n "$prev" ] && dep_args+=(--sbatch="--dependency=afterany:$prev")
      python experiment/congestion/gen_config.py \
        --victim allgather --aggressor "$AGG" --nodes "$N" \
        --victim-msgsize "$VM" --aggr-msgsize "$AGGR_MSG" \
        --iters "$ITERS" --warmup "$WARMUP" --walltime "$WALLTIME" \
        "${sbatch_args[@]}" "${dep_args[@]}" -o "$cfg" >/dev/null
      echo "=== submit: allgather vs $AGG | ${N} nodes | victim vec ${VM} B${prev:+  (after $prev)} ==="
      out="$(cinetic run -p "$PRESET" -c "$cfg")"; echo "$out"
      jid="$(echo "$out" | grep -oE 'Submitted batch job [0-9]+' | grep -oE '[0-9]+' | tail -1)"
      [ "$CHAIN" = 1 ] && prev="$jid"
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
