"""Lets `python -m tab ...` work.

The installed `tab` command is nicer, but pip may put it in a scripts folder
that is not on PATH — which it did on the machine this was built on. This entry
point always works, so the documentation can promise something that is true.
"""

from tab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
