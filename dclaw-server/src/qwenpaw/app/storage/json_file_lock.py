"""Bounded, process-shared locks for JSON read/modify/replace transactions."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
from threading import RLock
import time


class JsonFileBusyError(TimeoutError):
    pass


class JsonFileLock:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._lock = RLock()
        self._held: set[str] = set()

    @contextmanager
    def hold(self, path: Path):
        path = Path(path).resolve()
        if path == self.root or not path.is_relative_to(self.root):
            raise ValueError("lock target is outside repository")
        key = str(path)
        with self._lock:
            if key in self._held:
                yield
                return
            lock_path = (self.root / ".locks" / (
                hashlib.sha256(key.encode()).hexdigest() + ".lock"
            )).resolve()
            if not lock_path.is_relative_to(self.root):
                raise ValueError("lock path is outside repository")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+b") as handle:
                if os.name == "nt":
                    import msvcrt
                    if handle.seek(0, os.SEEK_END) == 0:
                        handle.write(b"\0")
                        handle.flush()
                    handle.seek(0)
                    acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    acquire = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    release = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                deadline = time.monotonic() + 5
                while True:
                    try:
                        acquire()
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise JsonFileBusyError(path.name)
                        time.sleep(0.01)
                self._held.add(key)
                try:
                    yield
                finally:
                    self._held.remove(key)
                    release()
