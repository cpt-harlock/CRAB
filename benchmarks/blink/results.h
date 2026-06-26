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

/* World rank 0 records this comm's membership into comm_manifest.csv. comm_id 0
   (re)creates the file with a header; comm_id > 0 appends a block. For a single
   COMM_WORLD run this yields the full node membership in one block.
   NOTE: only correct when world rank 0 is a member of `comm` (always true for
   COMM_WORLD). Sub-comm aggregation across disjoint comms is a later milestone. */
static void cin_write_manifest(int comm_id, int comm_size,
                               const char *all_names) {
  int world_rank;
  MPI_Comm_rank(MPI_COMM_WORLD, &world_rank);
  if (world_rank != 0)
    return;
  char path[4096];
  snprintf(path, sizeof(path), "%s/comm_manifest.csv", cin_results_dir());
  FILE *m = fopen(path, comm_id == 0 ? "w" : "a");
  if (m == NULL)
    return;
  if (comm_id == 0)
    fprintf(m, "comm,rank,node\n");
  for (int r = 0; r < comm_size; r++)
    fprintf(m, "%d,%d,%s\n", comm_id, r,
            &all_names[(size_t)r * MPI_MAX_PROCESSOR_NAME]);
  fclose(m);
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
  snprintf(filename, sizeof(filename), "%s/node_%s_rank%d.csv",
           cin_results_dir(), proc_name, rank);
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

  cin_write_manifest(comm_id, comm_size, all_names);
  free(all_names);
}

#endif /* CINETIC_RESULTS_H */
