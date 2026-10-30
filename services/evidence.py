"""Issue #8: Evidence files (images / PDFs) attached by agents while resolving a complaint."""
from datetime import datetime, timezone
from pathlib import Path

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 5   # per upload
SIGNATURES = {
    b"%PDF-": (".pdf", "application/pdf"),
    b"\xff\xd8\xff": (".jpg", "image/jpeg"),
    b"\x89PNG\r\n\x1a\n": (".png", "image/png"),
}


def file_type(head: bytes):
    """Return (extension, content_type) from the file signature, or None if not allowed."""
    for sig, kind in SIGNATURES.items():
        if head.startswith(sig):
            return kind
    return None


def validate(files):
    """`files` is a list of (filename, bytes). Return an error message, or None if all are valid."""
    if not files:
        return "At least one file is required"
    if len(files) > MAX_FILES:
        return f"At most {MAX_FILES} files can be uploaded at once"
    for name, data in files:
        if not data:
            return f"{name} is empty"
        if len(data) > MAX_FILE_BYTES:
            return f"{name} exceeds the 10 MB limit"
        if not file_type(data[:8]):
            return f"{name} is not a PDF, JPEG or PNG file"
    return None


def can_upload(user, complaint):
    """Assigned agent, or any supervisor / admin."""
    if user["role"] in ("supervisor", "admin"):
        return True
    return user["role"] == "agent" and complaint.get("assigned_to") == user["id"]


def store(complaint, files, user, uploads):
    """Save files under uploads/<ticket>/evidence/ and link them to the complaint. Returns the new entries."""
    folder = uploads / complaint["id"] / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    evidence = complaint.setdefault("evidence", [])
    now = datetime.now(timezone.utc).isoformat()
    added = []
    for name, data in files:
        ext, content_type = file_type(data[:8])
        eid = f"E{len(evidence) + 1}"
        path = folder / f"{eid}{ext}"
        path.write_bytes(data)
        entry = {"id": eid, "filename": Path(name).name[:255] or f"{eid}{ext}", "content_type": content_type,
                 "size": len(data), "path": path.relative_to(uploads.parent).as_posix(),
                 "uploaded_by": user["id"], "uploaded_by_name": user["name"], "uploaded_at": now}
        evidence.append(entry)
        added.append(entry)
    return added
