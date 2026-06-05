"""Enables `python -m logica_mind ...` (used by installed hooks when the
`logica-mind` console script isn't on the host's PATH)."""
from .cli import main

if __name__ == "__main__":
    main()
