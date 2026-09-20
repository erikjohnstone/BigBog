from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from bactalk.api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Export BACTalk's OpenAPI contract for the UI")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="bactalk-openapi-") as directory:
        app = create_app(run_root=Path(directory) / "runs")
        schema = app.openapi()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(arguments.output)


if __name__ == "__main__":
    main()
