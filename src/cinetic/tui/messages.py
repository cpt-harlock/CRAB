from textual.message import Message

class SaveConfiguration(Message):
    """
    Sent when the user requests to save the configuration.

    Signals the main application to collect the state from all relevant
    components (Application Forms, Benchmark Options, etc.) and start the
    save-to-file process.
    """
    pass

class LoadConfiguration(Message):
    """
    Sent when the user requests to load a configuration.

    Signals the main application to show a file picker and, once a file is
    chosen, load the data and distribute it to the appropriate TUI components.
    """
    pass

class RunBenchmark(Message):
    """
    Sent when the user presses the button to start the benchmark.

    Starts the benchmark run sequence, which includes:
    1. Collecting all data from the TUI.
    2. Switching to the log view.
    3. Starting the benchmark process in the background.
    """
    pass
