from __future__ import annotations

from pathlib import Path

import pytest

from src.shotcut import Shotcut

PROJECTS_DIR = Path.home() / "Videos" / "Projects"


def _find_projects() -> list[Path]:
    if not PROJECTS_DIR.exists():
        return []
    mlt_files = list(PROJECTS_DIR.rglob("*.mlt"))
    return [f for f in mlt_files if len(f.read_text()) < 500000]


def pytest_generate_tests(metafunc):
    if "project_path" in metafunc.fixturenames:
        projects = _find_projects()
        metafunc.parametrize(
            "project_path",
            [p for p in projects if "Repaired" not in p.stem],
            ids=[p.parent.name for p in projects if "Repaired" not in p.stem],
        )


@pytest.mark.slow
def test_project_roundtrip_loads(tmp_path: Path, project_path: Path) -> None:
    """Load and save a real project to a temp file without crashing."""
    sc = Shotcut(project_path)
    out = tmp_path / project_path.name
    sc.save(out)
    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.slow
def test_project_roundtrip_reloads(tmp_path: Path, project_path: Path) -> None:
    """Reload the saved copy and verify structural integrity."""
    sc = Shotcut(project_path)
    out = tmp_path / project_path.name
    sc.save(out)

    sc2 = Shotcut(out)
    assert len(sc2._tracks) > 0, f"No tracks after reload for {project_path}"
    assert len(sc2.assets) == len(sc.assets), "Asset count mismatch"
    assert sc2.timeline.duration > 0 or sc.timeline.duration == 0
    assert sc2.timeline.main_video is not None


@pytest.mark.slow
@pytest.mark.slow
def test_project_consecutive_saves_match(tmp_path: Path, project_path: Path) -> None:
    """Two consecutive saves from the same load produce identical XML."""
    sc = Shotcut(project_path)
    out1 = tmp_path / "save1.mlt"
    out2 = tmp_path / "save2.mlt"
    sc.save(out1)
    sc.save(out2)
    assert (
        out1.read_bytes() == out2.read_bytes()
    ), f"Consecutive saves differ for {project_path}"


@pytest.mark.slow
def test_project_roundtrip_idempotent(tmp_path: Path, project_path: Path) -> None:
    """After first save (which may defragment IDs), consecutive saves are stable."""
    gen0 = tmp_path / "gen0.mlt"
    sc = Shotcut(project_path)
    sc.save(gen0)

    sc2 = Shotcut(gen0)
    gen1 = tmp_path / "gen1.mlt"
    sc2.save(gen1)

    # gen0 may differ from gen1 (first save renumbers non-sequential IDs),
    # but subsequent saves from the same model state must be identical.
    sc3 = Shotcut(gen1)
    gen2 = tmp_path / "gen2.mlt"
    sc3.save(gen2)
    assert (
        gen1.read_bytes() == gen2.read_bytes()
    ), f"Save not idempotent for {project_path}"

    sc4 = Shotcut(gen2)
    gen3 = tmp_path / "gen3.mlt"
    sc4.save(gen3)
    assert (
        gen2.read_bytes() == gen3.read_bytes()
    ), f"Third save diverged for {project_path}"
