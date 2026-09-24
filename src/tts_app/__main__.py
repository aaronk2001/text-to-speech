from __future__ import annotations

import sys

from tts_app.app import App
from tts_app.log import setup_logging


def main() -> int:
    setup_logging()
    app = App(sys.argv)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
