#!/bin/bash
# Shared launch layer for the experiment/ runners. Source it AFTER cd-ing to the
# repo root. It gives every runner the SAME scheduler-option surface + optional
# job chaining + resilient submission, so all experiments launch identically and
# any option available in one runner is available in all of them.
#
# Env knobs (all optional; identical names across every runner). A runner may set
# its own *defaults* for these BEFORE sourcing this file (e.g. the Booster repro
# sets PARTITION/GRES/NO_AUTO_QOS) — values already in the environment win.
#   PRESET        cinetic preset                         (default leonardo)
#   PARTITION     --partition   (empty -> preset default)
#   ACCOUNT       --account
#   QOS           --qos
#   GRES          --gres
#   RESERVATION   --reservation (e.g. a maintenance window: maint_3006_boost)
#   EXTRA_SBATCH  space-separated extra "--flag=value" #SBATCH directives
#   NO_AUTO_QOS   1 -> pass --no-auto-qos to gen_config (skip its auto big-QOS)
#   CHAIN         1 -> serialize: each job --dependency=afterany:<prev> so only
#                      one runs at a time (avoids cross-job "false congestion")
#
# Usage in a runner loop:
#   source experiment/lib/launch.sh
#   for cell ...; do
#     launch_dep_args                         # -> LAUNCH_DEP_ARGS for this job
#     if python <gen_config.py> <axis-args> \
#          "${LAUNCH_GEN_ARGS[@]}" "${LAUNCH_DEP_ARGS[@]}" -o "$cfg" >/dev/null; then
#       launch_submit "$cfg" "human label"
#     fi
#   done
#   launch_footer

PRESET="${PRESET:-leonardo}"

# --- Site defaults: Leonardo *Booster*, default QOS, no reservation. Override any
#     from the environment. For a maintenance session, set the live values, e.g.
#       QOS=qos_special RESERVATION=maint_XXXX_boost
#     (get the reservation name from `scontrol show reservation`; both are usually
#     time-limited and disappear when the window ends). To run on DCGP instead:
#       PARTITION=dcgp_usr_prod NO_AUTO_QOS=0
# NB: PARTITION/QOS/RESERVATION use ${VAR-default} (no colon) so an explicit empty
# value (e.g. QOS=) CLEARS the default rather than re-substituting it.
PARTITION="${PARTITION-boost_usr_prod}"
ACCOUNT="${ACCOUNT:-}"
QOS="${QOS-}"
GRES="${GRES:-}"
RESERVATION="${RESERVATION-}"
NO_AUTO_QOS="${NO_AUTO_QOS:-1}"   # Booster default: don't auto-add the DCGP big-QOS
EXTRA_SBATCH="${EXTRA_SBATCH:-}"
CHAIN="${CHAIN:-0}"

# Static gen_config passthrough args, built once from the knobs above. Spliced
# into every gen_config call so the directives land in each generated config.
LAUNCH_GEN_ARGS=()
[ "$NO_AUTO_QOS" = 1 ] && LAUNCH_GEN_ARGS+=(--no-auto-qos)
[ -n "$PARTITION" ]   && LAUNCH_GEN_ARGS+=(--sbatch="--partition=$PARTITION")
[ -n "$ACCOUNT" ]     && LAUNCH_GEN_ARGS+=(--sbatch="--account=$ACCOUNT")
[ -n "$QOS" ]         && LAUNCH_GEN_ARGS+=(--sbatch="--qos=$QOS")
[ -n "$GRES" ]        && LAUNCH_GEN_ARGS+=(--sbatch="--gres=$GRES")
[ -n "$RESERVATION" ] && LAUNCH_GEN_ARGS+=(--sbatch="--reservation=$RESERVATION")
for _d in $EXTRA_SBATCH; do LAUNCH_GEN_ARGS+=(--sbatch="$_d"); done

LAUNCH_PREV=""        # last successfully-submitted job id (for the chain)
LAUNCH_N=0            # number of jobs submitted OK
LAUNCH_FAILED=0       # number of cells whose submission failed
LAUNCH_DEP_ARGS=()    # per-job chain dependency (refreshed by launch_dep_args)

# launch_dep_args: refresh LAUNCH_DEP_ARGS for the next job (chain on the previous
# one when CHAIN=1). Call once per cell, before generating its config.
launch_dep_args() {
  LAUNCH_DEP_ARGS=()
  [ "$CHAIN" = 1 ] && [ -n "$LAUNCH_PREV" ] && \
    LAUNCH_DEP_ARGS+=(--sbatch="--dependency=afterany:$LAUNCH_PREV")
}

# launch_submit <config> [label]: submit one config via the cinetic CLI. Tolerant
# of a single rejected submission (reports it, keeps going) so one bad cell never
# aborts the whole sweep. Updates the chain pointer + counters.
launch_submit() {
  local cfg="$1" label="${2:-$1}" out jid
  echo "=== submit: ${label}${LAUNCH_PREV:+  (after $LAUNCH_PREV)} ==="
  out="$(cinetic run -p "$PRESET" -c "$cfg" 2>&1)" || true
  echo "$out"
  jid="$(printf '%s\n' "$out" | grep -oE 'Submitted batch job [0-9]+' | grep -oE '[0-9]+' | tail -1)"
  if [ -n "$jid" ]; then
    [ "$CHAIN" = 1 ] && LAUNCH_PREV="$jid"
    LAUNCH_N=$((LAUNCH_N + 1))
  else
    echo "    !! submission FAILED for: $label (continuing)"
    LAUNCH_FAILED=$((LAUNCH_FAILED + 1))
  fi
}

# launch_footer: common closing summary.
launch_footer() {
  echo
  echo "Submitted $LAUNCH_N job(s) on preset '$PRESET'${PARTITION:+, partition $PARTITION}.${LAUNCH_FAILED:+  ($LAUNCH_FAILED failed)}"
  [ "$CHAIN" = 1 ] && echo "  CHAIN=1: serialized — each job runs only after the previous terminates."
}
