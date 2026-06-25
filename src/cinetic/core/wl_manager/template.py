from typing import List, Optional

class wl_manager:
    def __init__(self, ctx=None):
        # Backends receive the typed RuntimeContext; the abstract template just
        # stores it so concrete subclasses share a uniform constructor.
        self.ctx = ctx

    # Generates a script that can be used to run all the benchmarks specified in the schedule.
    def write_script(self, wlm_path, runner_args, schedules, nams, name, splits, node_file, ppn):
        pass

    # Returns a string that can be used to run command 'cmd'
    # on the nodes in 'node_list' with 'ppn' processes per node,
    # executing the optional "pre_commands" before cmd.
    def run_job(self, node_list, ppn, cmd, pre_commands: Optional[List[str]] = None):
        pass
        

