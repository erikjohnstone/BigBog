from __future__ import annotations

from pathlib import Path

import pytest

from bactalk.integrations.cdl import CdlTranslator


def test_cdl_translator_builds_non_shell_command(tmp_path: Path) -> None:
    checkout = tmp_path / "modelica-json"
    checkout.mkdir()
    (checkout / "app.js").write_text("// fixture", encoding="utf-8")
    source = tmp_path / "Controller.mo"
    source.write_text("model Controller end Controller;", encoding="utf-8")
    output = tmp_path / "cxf"

    command = CdlTranslator(checkout).build_command(source, output)

    assert command[0] == "node"
    assert command[1] == str(checkout / "app.js")
    assert command[command.index("-f") + 1] == str(source)
    assert command[command.index("-o") + 1] == "cxf"


def test_cdl_translator_supports_only_reviewed_modes(tmp_path: Path) -> None:
    checkout = tmp_path / "modelica-json"
    checkout.mkdir()
    (checkout / "app.js").write_text("// fixture", encoding="utf-8")
    source = tmp_path / "Controller.mo"
    source.write_text("model Controller end Controller;", encoding="utf-8")

    command = CdlTranslator(checkout).build_command(
        source,
        tmp_path / "out",
        mode="modelica",
    )
    assert command[command.index("-m") + 1] == "modelica"
    with pytest.raises(ValueError, match="unsupported Modelica translation mode"):
        CdlTranslator(checkout).build_command(
            source,
            tmp_path / "out",
            mode="arbitrary",  # type: ignore[arg-type]
        )


def test_cdl_translator_requires_checkout(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        CdlTranslator(tmp_path / "missing").build_command(
            tmp_path / "Controller.mo",
            tmp_path / "out",
        )


def test_cdl_source_inside_checkout_uses_relative_path(tmp_path: Path) -> None:
    checkout = tmp_path / "modelica-json"
    checkout.mkdir()
    (checkout / "app.js").write_text("// fixture", encoding="utf-8")
    source = checkout / "Controller.mo"
    source.write_text("model Controller end Controller;", encoding="utf-8")

    command = CdlTranslator(checkout).build_command(source, tmp_path / "out")

    assert command[command.index("-f") + 1] == "Controller.mo"


def test_cdl_translator_sets_modelica_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checkout = tmp_path / "modelica-json"
    checkout.mkdir()
    (checkout / "app.js").write_text("// fixture", encoding="utf-8")
    source = checkout / "Controller.mo"
    source.write_text("model Controller end Controller;", encoding="utf-8")
    library = tmp_path / "library"
    library.mkdir()
    observed: dict[str, str] = {}

    def fake_run(*args: object, **kwargs: object) -> None:
        observed.update(kwargs["env"])  # type: ignore[arg-type]
        output = tmp_path / "out" / "Controller.jsonld"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("bactalk.integrations.cdl.subprocess.run", fake_run)
    CdlTranslator(checkout, modelica_path=library).translate(source, tmp_path / "out")

    assert observed["MODELICAPATH"] == str(library.resolve())
