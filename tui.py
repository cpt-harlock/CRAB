import os
import sys

# Aggiunge la directory 'src' al path di Python per trovare il pacchetto 'cinetic'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

if __name__ == "__main__":
    # Quando il job SLURM viene lanciato, l'Engine ricostruisce il comando del worker
    # come "<python> <sys.argv[0]> --worker --workdir ...". Se la TUI è stata l'entry
    # point, sys.argv[0] è questo file: in worker mode NON dobbiamo riavviare la TUI
    # (che renderebbe codici ANSI nei log), ma eseguire la logica del worker.
    if "--worker" in sys.argv:
        from cinetic.cli.orchestrator import run_from_cli
        run_from_cli()
    else:
        from cinetic.tui.app import CineticApp
        app = CineticApp()
        app.run()
