from __future__ import annotations

from sion_api import migrate


def test_every_core_migration_file_is_in_the_runner():
    """A migrations/*.sql file the runner never applies is a table production never gets."""
    files = {path.stem for path in migrate.CORE_DIR.glob("*.sql")}
    sequenced = set(migrate.CORE_SEQUENCE) | {migrate.OPTIONAL_AGE}
    assert files - sequenced == set()
    assert sequenced - files == set()
    assert list(migrate.CORE_SEQUENCE) == sorted(migrate.CORE_SEQUENCE)
