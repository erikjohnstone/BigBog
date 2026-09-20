from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import schemathesis

from bactalk.api import create_app

_temporary_runs = TemporaryDirectory(prefix="bactalk-openapi-")
_schema = schemathesis.openapi.from_asgi(
    "/openapi.json",
    create_app(Path(_temporary_runs.name)),
).include(method="GET", path_regex=r"^/api/(health|runs)$")


@_schema.parametrize()
def test_read_api_matches_openapi_contract(case: schemathesis.Case) -> None:
    response = case.call()
    case.validate_response(response)
