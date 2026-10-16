"""Private file storage. Paths are generated server-side; client file names are
never used as paths, and files are only served through authorized endpoints."""

from __future__ import annotations

import mimetypes
import os
import uuid
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse

from .config import storage_dir

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
DOC_EXT = (".pdf", ".doc", ".docx")
RESUME_EXT = (".pdf", ".docx")   # what the resume parser can read
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
}


def safe_name(name: str | None) -> str:
    base = os.path.basename(name or "file")
    cleaned = "".join(c for c in base if c.isalnum() or c in "._- ").strip() or "file"
    return cleaned[:120]


# File signatures: the extension alone is not trusted.
_MAGIC = {".pdf": (b"%PDF",), ".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
          ".docx": (b"PK\x03\x04",), ".doc": (b"\xd0\xcf\x11\xe0",)}


def _content_matches(ext: str, data: bytes) -> bool:
    if ext == ".webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    sigs = _MAGIC.get(ext)
    if sigs is None:
        return True
    head = data[:1024].lstrip() if ext == ".pdf" else data
    return any(head.startswith(sig) for sig in sigs)


async def save_upload(upload: UploadFile, subdir: str, allowed: Iterable[str], max_bytes: int = MAX_UPLOAD_BYTES) -> tuple[str, str]:
    """Validate and store an upload. Returns (stored_path, original_file_name)."""
    original = safe_name(upload.filename)
    ext = os.path.splitext(original)[1].lower()
    allowed = tuple(allowed)
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(allowed)}")
    data = await upload.read()
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File is larger than {max_bytes // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if not _content_matches(ext, data):
        raise HTTPException(status_code=400, detail=f"The file content is not a valid {ext.lstrip('.').upper()} file")
    folder = storage_dir() / subdir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)
    return str(path), original


def save_bytes(data: bytes, subdir: str, ext: str) -> str:
    folder = storage_dir() / subdir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)
    return str(path)


def file_response(path: str | None, filename: str | None, download: bool = False) -> FileResponse:
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="File is not available")
    filename = filename or os.path.basename(path)
    ext = os.path.splitext(filename)[1].lower()
    media = MEDIA_TYPES.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media, filename=filename,
                        content_disposition_type="attachment" if download else "inline")


def remove_file(path: str | None) -> None:
    try:
        if path and Path(path).is_file() and str(storage_dir()) in str(Path(path).resolve()):
            Path(path).unlink()
    except OSError:
        pass
