import os

from typing import List, Optional

from cinetic.runtime import RuntimeContext

class wl_manager:
    def __init__(self, ctx: Optional[RuntimeContext] = None):
        # Fall back to the live environment when no context is injected, so the
        # backend still works if constructed directly (e.g. in a test).
        self.ctx = ctx if ctx is not None else RuntimeContext.from_env()

    # Generates a script that can be used to run all the benchmarks specified in the schedule.
    def write_script(self, runner_args, schedules, nams, name, splits, node_file, ppn):
        script=open(name,'w+')
        script.write('#!/bin/bash\nfor schedule in '+' '.join(schedules)+'\ndo\n')
        script.write('\tfor nam in '+' '.join(nams)+'\n\tdo\n')
        script.write('\t\tfor split in '+' '.join(splits)+'\n\t\tdo\n')
        script.write('\t\tpython3 runner.py "$schedule" '+node_file+' -am "$nam" -as "$split"'+runner_args+' -p '+str(ppn))
        script.write('\n\t\tdone\n\tdone\ndone')
        script.close()

    # Returns a string that can be used to run command 'cmd'
    # on the nodes in 'node_list' with 'ppn' processes per node,
    # executing "pre_commands" before cmd on each rank.
    def run_job(self, node_list, ppn, cmd, pre_commands: Optional[List[str]] = None):
        num_nodes=len(node_list)
        node_list_string=','.join(node_list)

        # --- WRAPPER LOGIC ---
        # If there are preliminary commands (e.g. 'module load openmpi'), run them
        # before the app command on each rank, silencing their output but keeping
        # the app's output (which we need for the measurements).
        if pre_commands and len(pre_commands) > 0:
            silenced_pre_commands = [f"{c} >/dev/null 2>&1" for c in pre_commands]
            full_sequence = " && ".join(silenced_pre_commands + [cmd])
            safe_sequence = full_sequence.replace("'", "'\\''")
            final_cmd = f"bash -c '{safe_sequence}'"
        else:
            final_cmd = cmd
        # ---------------------

        # OpenMPI does not forward non-OMPI_* env vars automatically: explicitly
        # forward the ones the binaries need (e.g. the per-node results dir).
        # That value is dynamic and per-experiment, so it stays in os.environ.
        env_forward = "-x CINETIC_NODE_RESULTS_DIR" \
            if "CINETIC_NODE_RESULTS_DIR" in os.environ else ""

        ctx = self.ctx
        parts = [
            ctx.mpirun,
            ctx.mpirun_map_by_node_flag,
            ctx.mpirun_additional_flags,
            ctx.pinning_flags,
            env_forward,
            ctx.mpirun_hostnames_flag,
            node_list_string,
            "-np " + str(ppn * num_nodes),
            final_cmd,
        ]
        job_cmd = " ".join(p for p in parts if p)
        print("[DEBUG]: MPI command is: " + job_cmd)
        return job_cmd
