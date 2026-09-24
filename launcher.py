from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _NullStream:
    encoding = "utf-8"
    errors = "replace"

    def write(self, _s):
        return 0

    def flush(self):
        pass

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("no fileno")


if sys.stdout is None:
    sys.stdout = _NullStream()
if sys.stderr is None:
    sys.stderr = _NullStream()

_LOG = Path(os.environ.get("LOCALAPPDATA", os.environ.get("TEMP", "."))) / "TTSApp" / "Logs" / "launcher.log"


def _trap_log(msg: str) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


try:
    from tts_app.__main__ import main

    if __name__ == "__main__":
        raise SystemExit(main())
except SystemExit:
    raise
except BaseException as e:
    _trap_log(f"FATAL: {e!r}\n{traceback.format_exc()}")
    raise
