"""Sprint 3 Task 1: concurrency-safe JSON storage shared by every file-backed store.

Before this, each request did read -> modify -> write on the JSON files with no locking and wrote them in
place, so simultaneous submissions could read the same list, generate the same ticket ID and overwrite each
other, and a reader could see a half-written file. Now every read-modify-write cycle holds LOCK and files are
replaced atomically.
"""
import json
import os
import tempfile
import threading
from functools import wraps
from pathlib import Path

LOCK = threading.RLock()   # re-entrant: a locked route may call services that lock again


def read_json(path, default):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, data):
    """Write to a temp file in the same folder, then atomically replace the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def synchronized(fn):
    """Decorator: run the whole function while holding the store lock."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with LOCK:
            return fn(*args, **kwargs)
    return wrapper
