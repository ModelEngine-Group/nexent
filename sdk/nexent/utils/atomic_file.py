import os
import stat
import tempfile
from pathlib import Path
from typing import Union


PathLike = Union[str, os.PathLike[str]]


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory sync after replacing a file."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: PathLike, data: bytes) -> None:
    """Write one file through a same-directory temporary file and atomic replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            descriptor = -1
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            os.fchmod(temporary_file.fileno(), existing_mode)
        os.replace(temporary_path, target)
        _fsync_directory(target.parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: PathLike, text: str, encoding: str = "utf-8") -> None:
    """Encode and atomically replace one text file."""
    atomic_write_bytes(path, text.encode(encoding))
