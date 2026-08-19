"""Index the compute app's artifacts into the master catalog.

Reads DATA_DIR (see source.py), computes rollups (rollups.py) and writes them
into PostgreSQL (writer.py). The API then answers every request from those rows
and never touches the filesystem.
"""

from .rollups import SpotRollup, SpotSpeciesRollup, DailyRollup, build
from .source import JobRef, SourceError, normalise_spot

__all__ = [
    "SpotRollup",
    "SpotSpeciesRollup",
    "DailyRollup",
    "build",
    "JobRef",
    "SourceError",
    "normalise_spot",
]
