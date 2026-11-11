"""Root-level pytest configuration.

The developer environment points ``SION_STORAGE_ROOT`` / ``SION_DRIVE_ROOT`` /
``GOOGLE_DRIVE_ROOT`` at the owner's real asset lake (the Google Drive folder
``SION-ONTOLOGY``). An app created inside a test inherits those variables, and
its export-on-write hook then exports the *test* database over the real
"latest" artifacts (``storage-manifest.json``, ``sion-latest.db``,
``sion-graph-latest.json``). That happened twice on 2026-11-11/12: a pytest run
overwrote the manifest with a 4/2/2 test dataset and the graph export with the
same, so the storage root no longer described the live database.

The variables are removed for the whole test session, so a test can never write
to the real asset lake. Tests that need a storage root point it at their own
temporary directory (``tests/test_drive_export.py``) and are unaffected.
"""

import os

for _key in ("SION_STORAGE_ROOT", "SION_DRIVE_ROOT", "GOOGLE_DRIVE_ROOT"):
    os.environ.pop(_key, None)
