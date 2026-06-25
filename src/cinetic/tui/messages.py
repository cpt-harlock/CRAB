from textual.message import Message

class SaveConfiguration(Message):
    """
    Messaggio inviato quando l'utente richiede di salvare la configurazione.
    
    Questo messaggio segnala all'applicazione principale di raccogliere lo stato
    da tutti i componenti rilevanti (Application Forms, Benchmark Options, etc.)
    e di avviare il processo di salvataggio su file.
    """
    pass

class LoadConfiguration(Message):
    """
    Messaggio inviato quando l'utente richiede di caricare una configurazione.

    Questo messaggio segnala all'applicazione principale di mostrare un selettore
    di file e, una volta scelto il file, di caricare i dati e distribuirli
    ai componenti TUI appropriati.
    """
    pass

class RunBenchmark(Message):
    """
    Messaggio inviato quando l'utente preme il pulsante per avviare il benchmark.

    Questo messaggio avvia la sequenza di esecuzione del benchmark, che include:
    1. Raccolta di tutti i dati dalla TUI.
    2. Passaggio alla vista dei log.
    3. Avvio del processo di benchmark in background.
    """
    pass
