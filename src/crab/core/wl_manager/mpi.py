import os

from typing import List, Optional

class wl_manager:
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
        # Se ci sono comandi preliminari (es. 'module load openmpi'), li eseguiamo
        # prima del comando dell'app su ogni rank, silenziando il loro output ma
        # mantenendo quello dell'app (che ci serve per le misure).
        if pre_commands and len(pre_commands) > 0:
            silenced_pre_commands = [f"{c} >/dev/null 2>&1" for c in pre_commands]
            full_sequence = " && ".join(silenced_pre_commands + [cmd])
            safe_sequence = full_sequence.replace("'", "'\\''")
            final_cmd = f"bash -c '{safe_sequence}'"
        else:
            final_cmd = cmd
        # ---------------------

        # OpenMPI non propaga automaticamente le env var non-OMPI_*: inoltriamo
        # esplicitamente quelle che servono ai binari (es. dir risultati per-nodo).
        env_forward = ""
        if "CRAB_NODE_RESULTS_DIR" in os.environ:
            env_forward = "-x CRAB_NODE_RESULTS_DIR "

        job_cmd = os.environ["CRAB_MPIRUN"] + " " + \
                  os.environ["CRAB_MPIRUN_MAP_BY_NODE_FLAG"] + " " + \
                  os.environ["CRAB_MPIRUN_ADDITIONAL_FLAGS"] + " " + \
                  os.environ["CRAB_PINNING_FLAGS"] + " " + \
                  env_forward + \
                  os.environ["CRAB_MPIRUN_HOSTNAMES_FLAG"] + " " + node_list_string + " " + \
                  "-np " + str(ppn*num_nodes) + " " + final_cmd
        print("[DEBUG]: MPI command is: " + job_cmd)
        return job_cmd
