"""End-to-end round-trip and operation tests for shotcut.py.

Focuses on properties that are reliably preserved through save/load cycles.
The Shotcut parser is a simplified model and does not preserve every XML detail
(e.g., individual filter elements on chains, all raw properties).
"""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from xml.etree.ElementTree import parse

import pytest

from src.shotcut import CollisionStrategy, Shotcut, TimelineClip, format_time

FILTER_TEST = Path("tests/filter_test.mlt")
TEST_MLT = Path("tests/test.mlt")
RETEST_MLT = Path("tests/retest.mlt")


# ===========================================================================
# Helpers
# ===========================================================================


def _xml_structure(path: Path) -> dict:
    """Extract structural counts preserved by the parser."""
    tree = parse(path)
    root = tree.getroot()
    chains = root.findall("chain")
    playlists = root.findall("playlist")
    tractors = root.findall("tractor")

    return {
        "profile": {
            k: root.find("profile").attrib.get(k)
            for k in (
                "frame_rate_num",
                "frame_rate_den",
                "height",
                "width",
                "display_aspect_num",
                "display_aspect_den",
            )
        },
        "chain_count": len(chains),
        "playlist_count": len(playlists),
        "tractor_count": len(tractors),
        "total_tractor_tracks": sum(len(t.findall("track")) for t in tractors),
    }


def _roundtrip(project: Shotcut, tmp_dir: Path) -> Path:
    out = tmp_dir / "roundtrip.mlt"
    project.save(out)
    return out


# ===========================================================================
# Round-trip tests
# ===========================================================================


class TestRoundTrip:
    """Load a .mlt, save immediately, reload, compare model-level properties."""

    def _check_model(self, p1: Shotcut, p2: Shotcut, label: str):
        e1 = len(p1._tracks)
        e2 = len(p2._tracks)
        assert e1 == e2, f"{label}: track count {e1} != {e2}"

        for idx in p1._tracks:
            t1 = p1._tracks[idx]
            t2 = p2._tracks[idx]
            assert len(t1.clips) == len(
                t2.clips
            ), f"{label} track {idx}: clip count {len(t1.clips)} != {len(t2.clips)}"
            assert len(t1.transitions) == len(
                t2.transitions
            ), f"{label} track {idx}: transition count {len(t1.transitions)} != {len(t2.transitions)}"

    @pytest.mark.parametrize(
        "mlt_path,label",
        [
            (FILTER_TEST, "filter_test"),
            (TEST_MLT, "test"),
            (RETEST_MLT, "retest"),
        ],
    )
    def test_model_preserved(self, mlt_path: Path, label: str, tmp_path: Path):
        p = Shotcut(mlt_path)
        saved = _roundtrip(p, tmp_path)
        p2 = Shotcut(saved)
        self._check_model(p, p2, label)

    @pytest.mark.parametrize(
        "mlt_path,label",
        [
            (FILTER_TEST, "filter_test"),
            (TEST_MLT, "test"),
            (RETEST_MLT, "retest"),
        ],
    )
    def test_profile_preserved(self, mlt_path: Path, label: str, tmp_path: Path):
        p = Shotcut(mlt_path)
        saved = _roundtrip(p, tmp_path)
        p2 = Shotcut(saved)
        for attr in ("framerate", "height", "width"):
            assert getattr(p, attr) == getattr(p2, attr), f"{label}: {attr} changed"

    @pytest.mark.parametrize(
        "mlt_path,label",
        [
            (FILTER_TEST, "filter_test"),
            (TEST_MLT, "test"),
            (RETEST_MLT, "retest"),
        ],
    )
    def test_tracks_preserved(self, mlt_path: Path, label: str, tmp_path: Path):
        p = Shotcut(mlt_path)
        saved = _roundtrip(p, tmp_path)
        p2 = Shotcut(saved)
        assert len(p._tracks) == len(p2._tracks)

    @pytest.mark.parametrize(
        "mlt_path,label",
        [
            (FILTER_TEST, "filter_test"),
            (TEST_MLT, "test"),
        ],
    )
    def test_clip_counts_preserved(self, mlt_path: Path, label: str, tmp_path: Path):
        p = Shotcut(mlt_path)
        saved = _roundtrip(p, tmp_path)
        p2 = Shotcut(saved)
        for idx in p._tracks:
            t1 = p._tracks[idx]
            t2 = p2._tracks[idx]
            assert len(t1.clips) == len(t2.clips), f"Track {idx} clip count mismatch"
            assert len(t1.transitions) == len(
                t2.transitions
            ), f"Track {idx} transition count mismatch"

    def test_assets_preserved(self, tmp_path: Path):
        p = Shotcut(FILTER_TEST)
        saved = _roundtrip(p, tmp_path)
        p2 = Shotcut(saved)
        assert len(p.assets) == len(p2.assets)
        for idx in p.assets:
            assert idx in p2.assets
            assert p.assets[idx].path.name == p2.assets[idx].path.name

    def test_consecutive_saves_identical(self, tmp_path: Path):
        p = Shotcut(FILTER_TEST)
        out1 = tmp_path / "save1.mlt"
        out2 = tmp_path / "save2.mlt"
        p.save(out1)
        p.save(out2)
        # Compare XML structures between consecutive saves
        s1 = _xml_structure(out1)
        s2 = _xml_structure(out2)
        assert s1 == s2


# ===========================================================================
# Basic load / model tests
# ===========================================================================


class TestLoad:
    def test_load_filter_test(self):
        p = Shotcut(FILTER_TEST)
        assert p.framerate > 0
        assert p.height > 0
        assert p.width > 0
        assert len(p.assets) > 0

    def test_load_test(self):
        p = Shotcut(TEST_MLT)
        assert len(p._tracks) >= 2
        assert len(p.assets) >= 1

    def test_load_retest(self):
        p = Shotcut(RETEST_MLT)
        assert len(p._tracks) >= 1

    def test_track_names(self):
        p = Shotcut(FILTER_TEST)
        for t in p._tracks.values():
            assert isinstance(t.name, str)
            assert len(t.name) > 0

    def test_main_tracks_exist(self):
        p = Shotcut(FILTER_TEST)
        assert p.timeline.main_video is not None
        assert p.timeline.main_audio is not None
        assert p.timeline.main_video.kind == "video"
        assert p.timeline.main_audio.kind == "audio"

    def test_clip_durations(self):
        p = Shotcut(FILTER_TEST)
        for t in p._tracks.values():
            for c in t.clips.values():
                assert c.duration > Decimal(0)

    def test_sorted_all_ordering(self):
        p = Shotcut(FILTER_TEST)
        for t in p._tracks.values():
            objects = t.sorted_all
            for i in range(len(objects) - 1):
                assert objects[i].start <= objects[i + 1].start


# ===========================================================================
# Operation tests
# ===========================================================================


class TestRemoveTime:
    def test_remove_zero_no_effect(self):
        p = Shotcut(FILTER_TEST)
        track = p._tracks[0]
        if not track.clips:
            pytest.skip("No clips on track")
        starts_before = {c.index: c.start for c in track.clips.values()}
        p.remove_time(track, Decimal(0))
        for c in track.clips.values():
            assert (
                c.start == starts_before[c.index]
            ), f"Clip {c.index} start changed after zero remove"


class TestCondenseClips:
    def test_condense_no_gap_is_noop(self, tmp_path: Path):
        p = Shotcut(FILTER_TEST)
        track = p._tracks[0]
        if not track.clips:
            pytest.skip("No clips")
        sc = track.sorted_clips

        pos = Decimal(0)
        for c in sc:
            c.start = pos
            track.clips[c.index] = c
            pos += c.duration

        starts_before = {c.index: c.start for c in track.clips.values()}
        p.condense_clips(track)
        for c in track.clips.values():
            assert (
                c.start == starts_before[c.index]
            ), f"Clip {c.index} start changed after condense on no-gap track"


class TestSplitClip:
    def test_split_halves(self):
        p = Shotcut(FILTER_TEST)
        track = p._tracks[0]
        if not track.clips:
            pytest.skip("No clips")
        clip = list(track.clips.values())[0]
        mid = clip.start + clip.duration / 2
        left, right = p._split_clip(clip, raw_time=mid)
        assert left.start == clip.start
        assert right.end == clip.end
        assert left.duration == right.duration
        assert left.bin_asset_id == right.bin_asset_id == clip.bin_asset_id

    def test_split_rejects_endpoints(self):
        p = Shotcut(FILTER_TEST)
        track = p._tracks[0]
        if not track.clips:
            pytest.skip("No clips")
        clip = list(track.clips.values())[0]
        with pytest.raises(AssertionError):
            p._split_clip(clip, raw_time=clip.start)
        with pytest.raises(AssertionError):
            p._split_clip(clip, raw_time=clip.end)

    def test_split_keeps_index(self):
        p = Shotcut(FILTER_TEST)
        track = p._tracks[0]
        if not track.clips:
            pytest.skip("No clips")
        clip = list(track.clips.values())[0]
        left, right = p._split_clip(clip, relative_time=clip.duration / 3)
        assert left.index == clip.index
        assert right.index != clip.index

    def test_rejects_both_times(self):
        p = Shotcut(FILTER_TEST)
        track = p._tracks[0]
        if not track.clips:
            pytest.skip("No clips")
        clip = list(track.clips.values())[0]
        with pytest.raises(AssertionError):
            p._split_clip(clip, raw_time=Decimal("5"), relative_time=Decimal("2"))

    def test_rejects_neither_time(self):
        p = Shotcut(FILTER_TEST)
        track = p._tracks[0]
        if not track.clips:
            pytest.skip("No clips")
        clip = list(track.clips.values())[0]
        with pytest.raises(AssertionError):
            p._split_clip(clip)


class TestCreateTrack:
    def test_create_track_increases_count(self):
        p = Shotcut(FILTER_TEST)
        count_before = len(p._tracks)
        t = p.create_track("test-video", "video")
        assert len(p._tracks) == count_before + 1
        assert t.name == "test-video"
        assert t.kind == "video"

    def test_create_audio_track(self):
        p = Shotcut(FILTER_TEST)
        t = p.create_track("test-audio", "audio")
        assert t.kind == "audio"

    def test_get_or_create_reuses(self):
        p = Shotcut(FILTER_TEST)
        t1 = p.get_or_create_track("shared", "video")
        t2 = p.get_or_create_track("shared", "video")
        assert t1.index == t2.index


class TestMovObj:
    def test_move_to_same_position(self):
        p = Shotcut(FILTER_TEST)
        track = p._tracks[0]
        if not track.clips:
            pytest.skip("No clips")
        clip = track.sorted_clips[0]
        orig_start = clip.start
        p._mov_obj(clip, new_time=clip.start)
        assert (
            clip.start == orig_start
        ), f"Clip moved despite same position: {orig_start} -> {clip.start}"

    def test_reject_on_collision(self):
        p = Shotcut(FILTER_TEST)
        track = p._tracks[0]
        clips = track.sorted_clips
        if len(clips) < 2:
            pytest.skip("Need at least 2 clips")
        first, second = clips[0], clips[1]
        with pytest.raises(ValueError, match="Collision"):
            p._mov_obj(first, new_time=second.start, strategy=CollisionStrategy.REJECT)


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_multiple_saves_stable(self, tmp_path: Path):
        """Consecutive saves should produce identical output (structural properties)."""
        p = Shotcut(FILTER_TEST)
        current = tmp_path / "gen0.mlt"
        p.save(current)

        structs = [_xml_structure(current)]
        for i in range(3):
            p = Shotcut(current)
            current = tmp_path / f"gen{i + 1}.mlt"
            p.save(current)
            structs.append(_xml_structure(current))

        # All structural properties should converge after first save
        for s in structs[1:]:
            assert s == structs[0], "Structure changed between save cycles"

    def test_asset_paths_valid(self):
        p = Shotcut(FILTER_TEST)
        for asset in p.assets.values():
            assert str(asset.path)
            assert asset.duration > Decimal(0)

    def test_save_does_not_crash(self, tmp_path: Path):
        p = Shotcut(FILTER_TEST)
        p.save(tmp_path / "test_save.mlt")
