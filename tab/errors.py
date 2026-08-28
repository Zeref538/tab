"""The two ways reading a receipt can fail, kept apart on purpose.

They live here rather than in tab.vision so that tab.pipeline can catch them
without importing the vision module, which pulls in jsonschema and is skipped
entirely for a PDF that carries its own text.
"""


class ExtractionFailed(RuntimeError):
    """The model was reached and could not produce a usable receipt.

    This is a fact about the document. Quarantining it is correct: reading it
    again would fail the same way.
    """


class ModelUnavailable(ExtractionFailed):
    """The model was never reached at all.

    This is a fact about the machine, and the difference is the whole reason
    the class exists. Quarantining records the file's hash and skips it for
    good, so treating a stopped Ollama as a bad receipt is how a five-minute
    restart silently eats every receipt that arrived during it.
    """
