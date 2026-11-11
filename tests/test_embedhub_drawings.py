"""The drawing benchmark from #106: render the Korean sheets and score them.

Offline CI renders the corpus and scores it with a fake embedder. The live nv-vl run is
opt-in and is skipped unless NVIDIA_API_KEY is set. Neither test writes a results file.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from sion_embedhub.cli import main

SHEETS = {"A-101", "A-102", "A-201", "A-301", "A-501", "A-601", "A-901", "S-201", "S-301"}
_KEY = re.compile(r"NVIDIA_API_KEY(_\d+)?")


def _has_nvidia_key() -> bool:
    return any(_KEY.fullmatch(name) and value.strip() for name, value in os.environ.items())


def _drop_nvidia_keys(monkeypatch) -> None:
    for name in list(os.environ):
        if _KEY.fullmatch(name):
            monkeypatch.delenv(name)


def _json_report(stdout: str) -> dict:
    return json.loads(stdout[stdout.index("{"):])


def test_offline_render_and_score(tmp_path, capsys):
    pytest.importorskip("ezdxf")
    pytest.importorskip("matplotlib")
    out = tmp_path / "corpus"
    rc = main(["bench-drawings", str(out), "--offline"])
    assert rc == 0
    report = _json_report(capsys.readouterr().out)

    renders = {path.stem: path for path in (out / "renders").glob("*.png")}
    assert set(renders) == SHEETS
    for path in renders.values():
        blob = path.read_bytes()
        assert blob.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(blob) > 2000

    assert report["live"] is False
    assert report["provider"] == "fake"
    assert report["docs"] == 9
    assert report["queries"] == 28
    assert "Not an NVIDIA result" in report["note"]
    image = report["indexed"]["offline:nv-vl@image:1024"]
    text = report["indexed"]["offline:nv-1b:1024"]
    same_model_text = report["indexed"]["offline:nv-vl:1024"]
    assert image == {"passages": 9, "images": 9}
    assert text["images"] == 0 and text["passages"] == 9
    assert same_model_text["images"] == 0 and same_model_text["passages"] == 9
    for block in (*report["models"].values(), report["rrf_fusion"]):
        for metric in ("recall@1", "recall@5", "recall@10", "mrr"):
            assert 0.0 <= block[metric] <= 1.0
    assert not (out / "results.json").exists()


def test_live_nv_vl_is_opt_in(tmp_path, monkeypatch, capsys):
    _drop_nvidia_keys(monkeypatch)

    def fake_build(out_dir):
        path = Path(out_dir)
        path.mkdir(parents=True, exist_ok=True)
        dataset = path / "drawings.jsonl"
        dataset.write_text("")
        return dataset

    monkeypatch.setattr("sion_embedhub.drawings.build_drawing_corpus", fake_build)
    rc = main(["bench-drawings", str(tmp_path / "corpus")])
    assert rc == 0
    report = _json_report(capsys.readouterr().out)
    assert report == {
        "live": False,
        "skipped": True,
        "reason": "NVIDIA_API_KEY not set",
        "rendered": True,
    }


def test_results_file_only_after_a_live_run(tmp_path, monkeypatch, capsys):
    _drop_nvidia_keys(monkeypatch)

    def fail_build(out_dir):
        raise AssertionError("refusing a results file must not render or score")

    monkeypatch.setattr("sion_embedhub.drawings.build_drawing_corpus", fail_build)
    dest = tmp_path / "results.json"
    assert main(["bench-drawings", str(tmp_path / "skipped"), "--results", str(dest)]) == 2
    assert main(["bench-drawings", str(tmp_path / "offline"), "--offline", "--results", str(dest)]) == 2
    assert not dest.exists()
    assert "refusing to write results" in capsys.readouterr().err


@pytest.mark.skipif(not _has_nvidia_key(), reason="NVIDIA_API_KEY not set; live nv-vl drawing benchmark is opt-in")
def test_bench_drawings_live_nv_vl(tmp_path, capsys):
    pytest.importorskip("ezdxf")
    pytest.importorskip("matplotlib")
    rc = main(["bench-drawings", str(tmp_path), "--models", "nv-vl:1024", "nv-vl@image:1024"])
    assert rc == 0
    report = _json_report(capsys.readouterr().out)
    assert report["live"] is True
    assert report["provider"] == "nvidia"
    assert report["docs"] == 9 and report["queries"] == 28
    assert set(report["models"]) == {"nv-vl:1024", "nv-vl@image:1024"}
    for block in report["models"].values():
        for metric in ("recall@1", "recall@5", "recall@10", "mrr"):
            assert 0.0 <= block[metric] <= 1.0
