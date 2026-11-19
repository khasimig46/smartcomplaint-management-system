"""Sprint 3 Task 1: concurrency-safe JSON storage shared by every file-backed store.

Before this, each request did read -> modify -> write on the JSON files with no locking and wrote them in
place, so simultaneous submissions could read the same list, generate the same ticket ID and overwrite each
other, and a reader could see a half-written file. Now every read-modify-write cycle holds LOCK and files are
replaced atomically.
"""
import collections
import json
import os
import tempfile
import threading
import time
from functools import wraps
from pathlib import Path

class FairRLock:
    """Re-entrant lock that hands itself to waiting threads in arrival order.

    threading.RLock is not fair: under load (TC20) a waiting request could lose the race again and again and
    wait 30 s+ while later requests went first. Here the releasing thread passes ownership straight to the
    longest-waiting thread.
    """

    def __init__(self):
        self._mutex = threading.Lock()
        self._owner, self._count = None, 0
        self._waiters = collections.deque()      # (thread id, Event) in arrival order

    def acquire(self):
        me = threading.get_ident()
        with self._mutex:
            if self._owner == me:
                self._count += 1
                return True
            if self._owner is None and not self._waiters:
                self._owner, self._count = me, 1
                return True
            turn = threading.Event()
            self._waiters.append((me, turn))
        turn.wait()                               # release() made us the owner before setting the event
        return True

    def release(self):
        with self._mutex:
            if self._owner != threading.get_ident():
                raise RuntimeError("cannot release un-acquired lock")
            self._count -= 1
            if self._count:
                return
            if self._waiters:
                self._owner, turn = self._waiters.popleft()
                self._count = 1
                turn.set()
            else:
                self._owner = None

    __enter__ = acquire

    def __exit__(self, *exc):
        self.release()


LOCK = FairRLock()   # re-entrant: a locked route may call services that lock again

# Last text read or written per file, keyed by its (mtime, size) stamp. A request reads the same JSON files
# many times (users, notifications, ...); re-opening them each time was the main cost under load (TC20).
# A changed stamp, including a change made outside this process, forces a re-read.
_cache = {}


def _stamp(path):
    st = os.stat(path)
    return st.st_mtime_ns, st.st_size


def read_json(path, default):
    """Return a fresh copy of the file's data (callers may change it), or `default` if it does not exist."""
    path = Path(path)
    try:
        stamp = _stamp(path)
    except FileNotFoundError:
        return default
    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return json.loads(cached[1])
    for attempt in range(50):           # Windows refuses the open while a save is swapping the file in
        try:
            text = path.read_text(encoding="utf-8")
            break
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.002)
    _cache[path] = (stamp, text)
    return json.loads(text)


def _replace(tmp, path, attempts=50):
    """os.replace, retried briefly: on Windows it fails with PermissionError while another thread has the target
    open for reading (reads do not take the lock). Seen in the TC20 load test; never happens on Linux."""
    for attempt in range(attempts):
        try:
            return os.replace(tmp, path)
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.002)


def write_json(path, data):
    """Write to a temp file in the same folder, then atomically replace the target.

    Compact JSON in one write (TC20): json.dump(..., indent=2) uses the pure-Python encoder and issues one file
    write per token, which made every save hold the store lock for ~0.25 s once the files grew.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        _replace(tmp, path)
        _cache[path] = (_stamp(path), text)
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
