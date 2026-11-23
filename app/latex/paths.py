"""Validation of manuscript-relative paths.

Manuscript files are addressed by POSIX-style relative paths such as `sections/intro.tex`.
These paths are materialized on disk for compilation and written into export archives, so
they are validated strictly: no absolute paths, no traversal, no hidden or control
characters, bounded depth and length.
"""
import re
from pathlib import PurePosixPath

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+\- ()]{0,119}$")
MAX_PATH_LENGTH = 400
MAX_DEPTH = 8

TEXT_EXTENSIONS = frozenset(
    {
        ".tex", ".bib", ".sty", ".cls", ".bst", ".bbx", ".cbx", ".def", ".cfg", ".clo", ".ltx",
        ".txt", ".md", ".csv", ".tsv", ".dat", ".tikz", ".pgf", ".latexmkrc", ".bbl", ".json", ".yaml", ".yml",
    }
)
BINARY_ASSET_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".pdf", ".eps", ".gif", ".webp", ".svg"})


class ManuscriptPathError(ValueError):
    pass


def normalize_manuscript_path(raw: str) -> str:
    if not isinstance(raw, str):
        raise ManuscriptPathError("Path must be a string.")
    candidate = raw.strip().replace("\\", "/")
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise ManuscriptPathError("Absolute paths are not allowed.")
    while "//" in candidate:
        candidate = candidate.replace("//", "/")
    candidate = candidate.strip("/")
    if not candidate:
        raise ManuscriptPathError("Path cannot be empty.")
    if len(candidate) > MAX_PATH_LENGTH:
        raise ManuscriptPathError("Path is too long.")
    if any(ord(ch) < 32 for ch in candidate):
        raise ManuscriptPathError("Path contains control characters.")
    parts = candidate.split("/")
    if len(parts) > MAX_DEPTH:
        raise ManuscriptPathError(f"Paths may be at most {MAX_DEPTH} levels deep.")
    for part in parts:
        if part in (".", "..") or not _SEGMENT_RE.match(part) or part.endswith(" ") or part.endswith("."):
            raise ManuscriptPathError(f"Invalid path segment '{part}'. Use letters, digits, '-', '_', '.' or spaces.")
    return "/".join(parts)


def is_text_path(path: str) -> bool:
    suffix = PurePosixPath(path).suffix.lower()
    return suffix in TEXT_EXTENSIONS or suffix == ""


def is_binary_asset_path(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in BINARY_ASSET_EXTENSIONS


def parent_folders(path: str) -> list[str]:
    parts = path.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]
