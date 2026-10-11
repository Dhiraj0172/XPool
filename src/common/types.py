from dataclasses import dataclass
from typing import NewType
import pathlib

# Common identifiers
ContentHash = NewType('ContentHash', str)  # Expected format: "sha256:..."
RecoveryID = NewType('RecoveryID', str)    # Expected format: timestamped UUID string
RequestID = NewType('RequestID', str)      # Correlation identifier

@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity."""
    token_id: str
    is_admin: bool = False

@dataclass(frozen=True)
class JulesPath:
    """
    Canonical, fully resolved absolute string path.
    Instantiation does not imply authorization logic has passed, only that
    the string has been resolved to eliminate traversal sequences.
    """
    raw_path: str

    @property
    def canonical_path(self) -> pathlib.Path:
        # Resolves the path to prevent arbitrary traversal ('../') escapes.
        # Enforce that the raw path string is not an absolute path trick bypassing the zone root entirely
        # before we even attempt to relative_to() it at the adapter.
        p = pathlib.Path(self.raw_path)
        # Using strict=False guarantees symlinks don't cause FileNotFoundError during resolution of missing targets
        return p.resolve(strict=False)

    def __str__(self) -> str:
        return str(self.canonical_path)
