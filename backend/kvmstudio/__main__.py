"""`python -m kvmstudio`, what the installed launcher runs."""

import sys

from .startup import run

if __name__ == "__main__":
    sys.exit(run())
