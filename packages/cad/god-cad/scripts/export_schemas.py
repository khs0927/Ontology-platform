import argparse
import json
from pathlib import Path

from god_cad.models import Drawing, Patch, PlanReport

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, contract in [("drawing", Drawing), ("patch", Patch), ("report", PlanReport)]:
        path = ROOT / "schemas" / f"{name}.schema.json"
        expected = json.dumps(contract.model_json_schema(), indent=2) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                raise SystemExit(f"Schema drift: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
