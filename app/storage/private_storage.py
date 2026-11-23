import hashlib
import os
import re
import uuid
from pathlib import Path

# Flexible research file-type classification (does not restrict researchers to a tiny hardcoded list)
RESEARCH_EXTENSION_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".tex": "application/x-tex",
    ".bib": "application/x-bibtex",
    ".sty": "text/plain",
    ".cls": "text/plain",
    ".bst": "text/plain",
    ".zip": "application/zip",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonl": "application/json",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".parquet": "application/octet-stream",
    ".npy": "application/octet-stream",
    ".npz": "application/octet-stream",
    ".h5": "application/octet-stream",
    ".nc": "application/octet-stream",
    ".py": "text/x-python",
    ".ipynb": "application/x-ipynb+json",
    ".r": "text/plain",
    ".rmd": "text/markdown",
    ".java": "text/x-java-source",
    ".c": "text/x-c",
    ".cpp": "text/x-c++",
    ".h": "text/x-c",
    ".hpp": "text/x-c++",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".sql": "application/sql",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
    ".toml": "application/toml",
    ".log": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".pt": "application/octet-stream",
    ".pth": "application/octet-stream",
    ".onnx": "application/octet-stream",
    ".safetensors": "application/octet-stream",
}

# Block raw OS binaries and active browser XSS documents when uploaded as disguised files
DISALLOWED_BINARY_EXTENSIONS = frozenset({".exe", ".dll", ".bat", ".cmd", ".msi", ".scr", ".com"})
DISALLOWED_MAGIC_PREFIXES = (
    b"<!DOCTYPE html",
    b"<html",
    b"<script",
    b"<svg",
    b"MZ",          # Windows PE binary executable
    b"\x7fELF",    # Linux ELF binary executable
)

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._() -]+")


class StorageSecurityError(ValueError):
    """Raised when a file upload or download violates security constraints."""


def sanitize_display_filename(filename: str) -> str:
    """Strip directory components and dangerous characters from a user-supplied filename."""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise StorageSecurityError("Invalid filename or path traversal attempt detected.")
    base = os.path.basename(filename).strip()
    cleaned = _SAFE_FILENAME_RE.sub("_", base)
    if not cleaned or cleaned.startswith("."):
        raise StorageSecurityError("Invalid filename.")
    return cleaned[:240]


def detect_and_validate_content(filename: str, content: bytes, max_bytes: int | None = None) -> str:
    """Validate content against binary executable / XSS signatures without arbitrary low size limits."""
    if len(content) == 0:
        raise StorageSecurityError("Empty files are not permitted.")
    if max_bytes is not None and max_bytes > 0 and len(content) > max_bytes:
        raise StorageSecurityError(f"File exceeds configured infrastructure limit of {max_bytes} bytes.")

    ext = Path(filename).suffix.lower()
    if ext in DISALLOWED_BINARY_EXTENSIONS:
        raise StorageSecurityError(f"Executable extension '{ext}' is not permitted.")

    head = content[:256].lstrip()
    for bad_prefix in DISALLOWED_MAGIC_PREFIXES:
        if head.lower().startswith(bad_prefix.lower()):
            raise StorageSecurityError("Executable binary or active HTML/script content is forbidden.")

    if ext == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise StorageSecurityError("File with .pdf extension does not have a valid %PDF- header.")
        return "application/pdf"
    if ext == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise StorageSecurityError("File with .png extension does not have a valid PNG signature.")
        return "image/png"
    if ext in (".jpg", ".jpeg"):
        if not content.startswith(b"\xff\xd8\xff"):
            raise StorageSecurityError("File with JPEG extension does not have a valid JPEG signature.")
        return "image/jpeg"

    return RESEARCH_EXTENSION_MEDIA_TYPES.get(ext, "application/octet-stream")


class PrivateStorageEngine:
    """Manages private file blobs and chunked/resumable uploads outside any public web root."""

    def __init__(self, root_dir: Path, max_upload_bytes: int | None = None) -> None:
        self.root_dir = root_dir.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir = (self.root_dir / "_staging").resolve()
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        # No arbitrary low application cap unless explicitly configured by infrastructure
        self.max_upload_bytes = max_upload_bytes

    def store_bytes(self, project_id: str, display_name: str, content: bytes) -> dict[str, object]:
        safe_name = sanitize_display_filename(display_name)
        media_type = detect_and_validate_content(safe_name, content, None)
        checksum = hashlib.sha256(content).hexdigest()
        storage_key = f"{project_id}/{uuid.uuid4().hex}.bin"
        target_path = (self.root_dir / storage_key).resolve()
        target_path.relative_to(self.root_dir)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        return {
            "original_name": safe_name,
            "storage_key": storage_key,
            "size_bytes": len(content),
            "media_type": media_type,
            "checksum_sha256": checksum,
        }

    def init_staging_file(self, upload_id: str) -> str:
        temp_key = f"_staging/{upload_id}.part"
        target_path = (self.root_dir / temp_key).resolve()
        target_path.relative_to(self.root_dir)
        target_path.write_bytes(b"")
        return temp_key

    def append_staging_chunk(self, temp_key: str, chunk: bytes) -> int:
        if ".." in temp_key or not temp_key.startswith("_staging/"):
            raise StorageSecurityError("Invalid staging key.")
        target_path = (self.root_dir / temp_key).resolve()
        target_path.relative_to(self.root_dir)
        with open(target_path, "ab") as f:
            f.write(chunk)
        return target_path.stat().st_size

    def finalize_staging_upload(self, project_id: str, display_name: str, temp_key: str) -> dict[str, object]:
        """Validate and move a completed staging file into storage without loading it into memory."""
        if ".." in temp_key or not temp_key.startswith("_staging/"):
            raise StorageSecurityError("Invalid staging key.")
        staging_path = (self.root_dir / temp_key).resolve()
        staging_path.relative_to(self.root_dir)
        if not staging_path.is_file():
            raise FileNotFoundError("Staging upload file not found.")
        safe_name = sanitize_display_filename(display_name)
        with open(staging_path, "rb") as fh:
            head = fh.read(4096)
        media_type = detect_and_validate_content(safe_name, head, None)
        digest = hashlib.sha256()
        with open(staging_path, "rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(block)
        size = staging_path.stat().st_size
        storage_key = f"{project_id}/{uuid.uuid4().hex}.bin"
        target_path = (self.root_dir / storage_key).resolve()
        target_path.relative_to(self.root_dir)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_path, target_path)
        return {
            "original_name": safe_name,
            "storage_key": storage_key,
            "size_bytes": size,
            "media_type": media_type,
            "checksum_sha256": digest.hexdigest(),
        }

    def remove_staging_file(self, temp_key: str) -> None:
        if ".." in temp_key or not temp_key.startswith("_staging/"):
            return
        staging_path = (self.root_dir / temp_key).resolve()
        try:
            staging_path.relative_to(self.root_dir)
            staging_path.unlink(missing_ok=True)
        except ValueError:
            return

    def read_bytes(self, storage_key: str) -> bytes:
        if ".." in storage_key or storage_key.startswith("/"):
            raise StorageSecurityError("Invalid storage key.")
        target_path = (self.root_dir / storage_key).resolve()
        try:
            target_path.relative_to(self.root_dir)
        except ValueError as exc:
            raise StorageSecurityError("Path traversal blocked.") from exc
        if not target_path.is_file():
            raise FileNotFoundError("Stored file blob not found.")
        return target_path.read_bytes()

    def delete_key(self, storage_key: str) -> None:
        if ".." in storage_key or storage_key.startswith("/"):
            return
        target_path = (self.root_dir / storage_key).resolve()
        try:
            target_path.relative_to(self.root_dir)
            if target_path.is_file():
                target_path.unlink()
        except ValueError:
            return

    def _resolve_key(self, storage_key: str) -> Path:
        if not storage_key or ".." in storage_key or storage_key.startswith("/") or "\\" in storage_key:
            raise StorageSecurityError("Invalid storage key.")
        target_path = (self.root_dir / storage_key).resolve()
        try:
            target_path.relative_to(self.root_dir)
        except ValueError as exc:
            raise StorageSecurityError("Path traversal blocked.") from exc
        return target_path

    def exists(self, storage_key: str) -> bool:
        try:
            return self._resolve_key(storage_key).is_file()
        except StorageSecurityError:
            return False

    def path_for(self, storage_key: str) -> Path:
        """Filesystem path of a stored blob, for streaming responses without loading it into memory."""
        target = self._resolve_key(storage_key)
        if not target.is_file():
            raise FileNotFoundError("Stored file blob not found.")
        return target

    def staging_size(self, temp_key: str) -> int:
        if ".." in temp_key or not temp_key.startswith("_staging/"):
            raise StorageSecurityError("Invalid staging key.")
        path = self._resolve_key(temp_key)
        return path.stat().st_size if path.is_file() else 0

    def cleanup_abandoned_staging(self, live_keys: set[str], max_age_seconds: int = 86400) -> int:
        """Delete staging files that no active upload session references and that are older than max_age."""
        import time

        removed = 0
        cutoff = time.time() - max_age_seconds
        for child in self.staging_dir.glob("*.part"):
            key = f"_staging/{child.name}"
            try:
                if key not in live_keys and child.stat().st_mtime < cutoff:
                    child.unlink()
                    removed += 1
            except OSError:
                continue
        return removed
