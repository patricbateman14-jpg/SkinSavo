"""Run inside the existing Railway service/volume; never substitute a dev database."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from storage import StorageUnavailable
from storage_migration import (
    abort_uncommitted_migration,
    migrate_to_postgres,
    source_metadata,
)


def run():
    parser = argparse.ArgumentParser(
        description="Verified SkinSavo SQLite -> Supabase migration"
    )
    parser.add_argument(
        "--source",
        default=main.DB_PATH,
        help="Existing production SQLite DATABASE_PATH",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--check",
        action="store_true",
        help="Inspect readiness without freezing or writing data",
    )
    actions.add_argument(
        "--abort-uncommitted",
        action="store_true",
        help="Thaw SQLite only after proving PostgreSQL has no committed import/data",
    )
    args = parser.parse_args()
    if not main.DATABASE_URL:
        raise StorageUnavailable("Set the server-only DATABASE_URL first")
    if args.check:
        metadata = source_metadata(args.source)
        with main.database.postgres_connection() as target:
            target.execute("SELECT 1").fetchone()
        print(
            json.dumps(
                {
                    "source_prepared": True,
                    "source_frozen": metadata.get("frozen") == "1",
                    "target_connected": True,
                }
            )
        )
    elif args.abort_uncommitted:
        abort_uncommitted_migration(main.database, args.source)
        print("Uncommitted migration aborted; SQLite is writable again.")
    else:
        print(
            json.dumps(migrate_to_postgres(main.database, args.source), sort_keys=True)
        )
    main.database.close()


if __name__ == "__main__":
    try:
        run()
    except StorageUnavailable as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
