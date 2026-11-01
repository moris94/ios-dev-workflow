#!/usr/bin/env python3
"""Hook entrypoint: stdlib-only, so it works with the system python3."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from appfactory.guards import main  # noqa: E402

sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
