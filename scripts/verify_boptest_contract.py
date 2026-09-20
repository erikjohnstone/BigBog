from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).parents[1]
LOCK = json.loads((ROOT / "ops" / "stack.lock.json").read_text(encoding="utf-8"))
BOPTEST_REVISION = LOCK["components"]["boptest"]["revision"]
OPENAPI_URL = (
    "https://raw.githubusercontent.com/ibpsa/project1-boptest/"
    f"{BOPTEST_REVISION}/service/web/server/docs/openapi.yaml"
)

EXPECTED_METHODS = {
    "/version": "get",
    "/testcases": "get",
    "/testcases/{testcase_name}/select": "post",
    "/initialize/{testid}": "put",
    "/step/{testid}": "put",
    "/inputs/{testid}": "get",
    "/measurements/{testid}": "get",
    "/advance/{testid}": "post",
    "/kpi/{testid}": "get",
    "/stop/{testid}": "put",
}


def main() -> None:
    with urlopen(OPENAPI_URL, timeout=30) as response:
        document = yaml.safe_load(response.read())
    paths = document["paths"]
    for endpoint, method in EXPECTED_METHODS.items():
        if endpoint not in paths or method not in paths[endpoint]:
            raise SystemExit(f"BOPTEST contract missing {method.upper()} {endpoint}")

    select = paths["/testcases/{testcase_name}/select"]["post"]
    if select.get("requestBody", {}).get("required") is not True:
        raise SystemExit("BOPTEST selection body is no longer required; review the client")
    stop_content = paths["/stop/{testid}"]["put"]["responses"]["200"]["content"]
    if "text/plain" not in stop_content:
        raise SystemExit("BOPTEST stop response is no longer text/plain; review the client")

    print(
        f"verified {len(EXPECTED_METHODS)} BOPTEST operations against "
        f"{BOPTEST_REVISION[:12]}"
    )


if __name__ == "__main__":
    main()
