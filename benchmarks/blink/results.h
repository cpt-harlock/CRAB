#ifndef CINETIC_RESULTS_H
#define CINETIC_RESULTS_H

/* CINETIC standardized per-node results writer.
 *
 * Every benchmark already times its operation per iteration into a ring buffer;
 * this header turns that into the one per-node CSV the analyzer consumes, so
 * point-to-point and collective benchmarks are reported uniformly. See
 * PLAN_OUTPUT_STANDARDIZATION.md.
 *
 * Unified schema (parsed by header name; a strict superset of the historic
 * tournament format, so old files still parse):
 *
 *   node,rank,op,comm,sample,phase,peer_node,peer_rank,bytes,ops,duration_s
 *
 *   op         operation tag (e.g. "pairwise_fd", "allreduce", "alltoall")
 *   comm       communicator id (0 = COMM_WORLD); links to comm_manifest.csv
 *   phase      sub-step within the op (tournament round / ring step); -1 if n/a
 *   peer_*     the single counterparty for pairwise rows; empty / -1 for
 *              collective rows (peer set = the comm — see the manifest)
 *   bytes      bandwidth basis: bytes moved by THIS rank for this sample
 *              (the caller computes it per the op's algorithm, busbw convention)
 *   ops        latency basis: latency-units folded into this sample
 *
 * The analyzer then computes, uniformly: bandwidth = bytes/duration_s and
 * latency = duration_s/ops.
 *
 * Header-only (all `static`), matching common.h. Self-contained: it takes the
 * ring buffers and counters as parameters rather than relying on common.h
 * globals, so it can be included alongside common.h without redefining anything.
 */

#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Experiment output dir exported by CINETIC; legacy CRAB_ name accepted;
   fall back to the current working directory. */
static const char *cin_results_dir(void) {
  const char *d = getenv("CINETIC_NODE_RESULTS_DIR");
  if (d == NULL || d[0] == '\0')
    d = getenv("CRAB_NODE_RESULTS_DIR");
  if (d == NULL || d[0] == '\0')
    d = ".";
  return d;
}

/* App id within the experiment (CINETIC_APP_ID, set per app by the engine).
   Multiple apps in one experiment share the results dir, each with its own
   MPI_COMM_WORLD (ranks 0..n-1), so per-node filenames must be namespaced by
   app id or co-located apps would clobber each other. Defaults to 0 (a single
   app / a direct mpirun), which yields filenames a legacy-format analyzer still
   globs as node_*.csv / comm_manifest_*.csv. */
static int cin_app_id(void) {
  const char *s = getenv("CINETIC_APP_ID");
  if (s == NULL || s[0] == '\0')
    return 0;
  return atoi(s);
}

/* Whether this app should emit standardized per-node output. The engine sets
   CINETIC_COLLECT=0 for non-collecting apps (e.g. aggressors) so they don't
   write useless dumps; unset/non-zero => emit (preserves direct-mpirun use).
   This is per-app (all ranks share the value), so the collective MPI calls in
   the writers are entered or skipped uniformly — no deadlock. */
static int cin_collect_enabled(void) {
  const char *s = getenv("CINETIC_COLLECT");
  return !(s != NULL && s[0] == '0' && s[1] == '\0');
}

/* Write comm_manifest.csv (comm,rank,node) for the whole job, race-free.
 *
 * Each world rank passes the id of the communicator it ran the op on
 * (``my_comm_id``); every rank in the same communicator must pass the same id,
 * and the ids must be unique across distinct communicators (e.g. the
 * MPI_Comm_split color). All ids + hostnames are gathered to WORLD rank 0, which
 * groups ranks by id (members in ascending world-rank order — matching
 * MPI_Comm_split's key ordering) and writes the file **once**. This supports
 * many sub-communicators (a split sweep) without the multiple concurrent
 * writers the old per-comm writer had.
 *
 * Collective: call from every rank of MPI_COMM_WORLD after a barrier. */
static void cin_write_manifest(int my_comm_id) {
  if (!cin_collect_enabled())
    return;
  int wrank, wsize;
  MPI_Comm_rank(MPI_COMM_WORLD, &wrank);
  MPI_Comm_size(MPI_COMM_WORLD, &wsize);

  char proc[MPI_MAX_PROCESSOR_NAME];
  int nl = 0;
  memset(proc, 0, sizeof(proc));
  if (MPI_Get_processor_name(proc, &nl) != MPI_SUCCESS)
    snprintf(proc, sizeof(proc), "unknown");

  char *names = NULL;
  int *ids = NULL;
  if (wrank == 0) {
    names = (char *)malloc((size_t)wsize * MPI_MAX_PROCESSOR_NAME);
    ids = (int *)malloc(sizeof(int) * wsize);
    if (names == NULL || ids == NULL) {
      fprintf(stderr, "Failed to allocate manifest buffer\n");
      MPI_Abort(MPI_COMM_WORLD, 1);
    }
  }
  MPI_Gather(proc, MPI_MAX_PROCESSOR_NAME, MPI_CHAR, names,
             MPI_MAX_PROCESSOR_NAME, MPI_CHAR, 0, MPI_COMM_WORLD);
  MPI_Gather(&my_comm_id, 1, MPI_INT, ids, 1, MPI_INT, 0, MPI_COMM_WORLD);

  if (wrank != 0)
    return;
  char path[4096];
  snprintf(path, sizeof(path), "%s/comm_manifest_app%d.csv", cin_results_dir(),
           cin_app_id());
  FILE *m = fopen(path, "w");
  if (m != NULL) {
    fprintf(m, "comm,rank,node\n");
    char *done = (char *)calloc((size_t)wsize, 1);
    for (int r = 0; r < wsize; r++) {
      if (done && done[r])
        continue;
      int id = ids[r], sub = 0;
      for (int s = r; s < wsize; s++) {
        if (ids[s] == id) {
          fprintf(m, "%d,%d,%s\n", id, sub++,
                  &names[(size_t)s * MPI_MAX_PROCESSOR_NAME]);
          if (done)
            done[s] = 1;
        }
      }
    }
    free(done);
    fclose(m);
  }
  free(names);
  free(ids);
}

/* Write this rank's measured samples to node_<host>_rank<r>.csv in the unified
   schema, and contribute to comm_manifest.csv.
 *
 *   op, comm_id        operation tag and communicator id for the rows
 *   comm               the communicator the op ran on (for rank/size/hostnames)
 *   durations          ring buffer of per-sample wall-times (len max_samples)
 *   peer               parallel ring buffer of peer ranks; NULL => collective
 *                      (peer_rank written as -1, peer_node empty)
 *   phase              parallel ring buffer of phase ids; NULL => -1
 *   bytes_per_sample   bandwidth basis (constant within the run)
 *   ops_per_sample     latency basis (constant within the run)
 *   curr_iters, max_samples, warm_up_iters
 *                      ring-buffer state, exactly as common.h tracks it; the LRU
 *                      wrap reconstruction mirrors write_results().
 *
 * Collective: every rank must call this after a shared barrier on `comm` (the
 * MPI_Allgather below is collective over `comm`).
 */
static void cin_write_node_results(const char *op, int comm_id, MPI_Comm comm,
                                   const double *durations, const int *peer,
                                   const int *phase, double bytes_per_sample,
                                   double ops_per_sample, int curr_iters,
                                   int max_samples, int warm_up_iters) {
  if (!cin_collect_enabled())
    return;
  int rank, comm_size;
  MPI_Comm_rank(comm, &rank);
  MPI_Comm_size(comm, &comm_size);

  /* this rank's hostname (zero-padded: the whole field is gathered) */
  char proc_name[MPI_MAX_PROCESSOR_NAME];
  int name_len = 0;
  memset(proc_name, 0, sizeof(proc_name));
  if (MPI_Get_processor_name(proc_name, &name_len) != MPI_SUCCESS)
    snprintf(proc_name, sizeof(proc_name), "unknown");

  /* gather every rank's hostname so a peer rank maps to its node */
  char *all_names =
      (char *)malloc((size_t)comm_size * MPI_MAX_PROCESSOR_NAME);
  if (all_names == NULL) {
    fprintf(stderr, "Failed to allocate a buffer on rank %d\n", rank);
    MPI_Abort(comm, 1);
  }
  MPI_Allgather(proc_name, MPI_MAX_PROCESSOR_NAME, MPI_CHAR, all_names,
                MPI_MAX_PROCESSOR_NAME, MPI_CHAR, comm);

  /* ordered sample window: same LRU reconstruction as write_results().
     idx(i) maps the chronological position i to its ring-buffer slot. */
  int wrapped = (curr_iters > max_samples);
  int num_samples = wrapped ? max_samples : (curr_iters - warm_up_iters);
  int base = wrapped ? (curr_iters % max_samples) : warm_up_iters;
  if (num_samples < 0)
    num_samples = 0;

  char filename[4096];
  snprintf(filename, sizeof(filename), "%s/node_app%d_%s_rank%d.csv",
           cin_results_dir(), cin_app_id(), proc_name, rank);
  FILE *f = fopen(filename, "w");
  if (f == NULL) {
    fprintf(stderr, "Rank %d could not open %s for writing\n", rank, filename);
    free(all_names);
    return;
  }

  fprintf(f, "node,rank,op,comm,sample,phase,peer_node,peer_rank,bytes,ops,"
             "duration_s\n");
  for (int i = 0; i < num_samples; i++) {
    int idx = wrapped ? (base + i) % max_samples : base + i;
    int pr = peer ? peer[idx] : -1;
    int ph = phase ? phase[idx] : -1;
    const char *pname = (pr >= 0 && pr < comm_size)
                            ? &all_names[(size_t)pr * MPI_MAX_PROCESSOR_NAME]
                            : "";
    fprintf(f, "%s,%d,%s,%d,%d,%d,%s,%d,%.0f,%.0f,%.9f\n", proc_name, rank, op,
            comm_id, i, ph, pname, pr, bytes_per_sample, ops_per_sample,
            durations[idx]);
  }
  fclose(f);
  free(all_names);
}

#endif /* CINETIC_RESULTS_H */
