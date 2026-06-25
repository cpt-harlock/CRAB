from typing import List, Optional

from cinetic.runtime import RuntimeContext

class wl_manager:
    def __init__(self, ctx: Optional[RuntimeContext] = None):
        # Fall back to the live environment when no context is injected.
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
    # executing "pre_commands" before cmd
    def run_job(self, node_list: List[str], ppn: int, cmd: str, pre_commands: Optional[List[str]] = None):
        num_nodes = len(node_list)
        node_list_string = ','.join(node_list)
        node_list_arg = '--nodelist ' + node_list_string

        # --- Wrapper logic ---
        if pre_commands and len(pre_commands) > 0:
            # 1. Silence each preliminary command by appending ' >/dev/null 2>&1'
            #    to every header command. This discards both stdout and stderr of
            #    the modules. To see errors but not output, use only ' >/dev/null'.
            silenced_pre_commands = [f"{c} >/dev/null 2>&1" for c in pre_commands]

            # 2. Join the silenced commands and the final command with '&&'.
            #    Note: cmd (the app) is NOT silenced — we need its output!
            full_sequence = " && ".join(silenced_pre_commands + [cmd])

            # 3. Escape single quotes for safety inside bash -c '...'.
            safe_sequence = full_sequence.replace("'", "'\\''")

            # 4. Wrap everything in bash -c.
            final_cmd = f"bash -c '{safe_sequence}'"
        else:
            # No pre-commands, run directly (legacy/simple mode).
            final_cmd = cmd
        # --------------------------

        slurm_string = (
            'srun --export=ALL ' +
            node_list_arg + ' ' +
            self.ctx.pinning_flags + ' ' +
            '-n ' + str(ppn * num_nodes) + ' ' +
            '-N ' + str(num_nodes) + ' ' +
            final_cmd  # the computed command (wrapped or raw)
        ).strip() 

        print("[DEBUG]: SLURM command is: " + slurm_string)
        return slurm_string
