"""Test-wide isolation from the developer's real database.

`settings.database_path` defaults to `data/betswin.db`, relative to wherever
pytest was started. Several tests boot the full API through `TestClient`, which
opens that path -- so a run inherited whatever the previous run, or a local
`python -m arbengine.main`, had left in it. `test_api_unwind_and_resolve` is the
one that noticed: it asserts a refused unwind leaves the position unsettled, and
a settled row of the same id left over from an earlier run made it fail. CI
never saw it, because CI always starts from an empty checkout.

Pointing the session at a throwaway file makes every local run start where CI's
does. This happens at import rather than in a fixture: pytest imports conftest
before the test modules, and `arbengine.config` builds its settings singleton
the moment one of them imports it -- by the time any fixture runs, the path has
already been read.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="betswin-tests-"))

os.environ["DATABASE_PATH"] = str(_TMP / "test.db")
os.environ.setdefault("AUTOSTART_SCANNER", "false")


@atexit.register
def _cleanup() -> None:
    # The engine holds the SQLite handle until interpreter shutdown, so this
    # runs late deliberately. Failure to remove it is not worth failing a test
    # run over -- it is a temp directory the OS will reap.
    shutil.rmtree(_TMP, ignore_errors=True)
