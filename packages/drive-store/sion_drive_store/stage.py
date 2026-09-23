from __future__ import annotations

import argparse
import json

from .store import DriveLayout, LocalContentAddressedStore


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage a file into the Sion content-addressed artifact lake."
    )
    parser.add_argument("file")
    parser.add_argument("--store-root", required=True)
    parser.add_argument(
        "--drive-project-root",
        default="AEC-INTELLIGENCE/01_PROJECTS/SION-ONTOLOGY",
    )
    args = parser.parse_args()

    store = LocalContentAddressedStore(
        args.store_root,
        drive_layout=DriveLayout(project_root=args.drive_project_root),
    )
    descriptor = store.put_file(args.file)
    print(json.dumps(descriptor.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
