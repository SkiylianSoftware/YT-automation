from __future__ import annotations

import json
from argparse import Namespace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from xml.etree.ElementTree import parse

import pytest

from src.background_music import Song, background_music, find_song_locations, find_songs, insert_songs, pack_bin
from src.shotcut import Marker, Shotcut, format_time, str_to_timedelta, timedelta_to_str

TEST_MLT = Path("tests/filter_test.mlt")


@pytest.fixture
def shotcut() -> Shotcut:
    return Shotcut(TEST_MLT)


def test_find_songs_returns_list(shotcut: Shotcut) -> None:
    songs = find_songs(shotcut, [Path.home() / "Videos"])
    assert isinstance(songs, list)


def test_find_songs_filters_by_music_dir(shotcut: Shotcut) -> None:
    songs = find_songs(shotcut, [Path("/nonexistent")])
    assert len(songs) == 0


def test_find_songs_returns_song_objects(shotcut: Shotcut) -> None:
    songs = find_songs(shotcut, [Path.home() / "Videos"])
    if songs:
        song = songs[0]
        assert isinstance(song.id, int)
        assert isinstance(song.name, str)
        assert isinstance(song.length, timedelta)
        assert isinstance(song.path, Path)


def test_find_markers_returns_list_of_tuples(shotcut: Shotcut) -> None:
    markers = shotcut.find_markers()
    assert isinstance(markers, list)
    for m in markers:
        assert isinstance(m, tuple)
        assert len(m) == 2
        assert isinstance(m[0], Decimal)
        assert isinstance(m[1], Decimal)


def test_find_markers_no_markers_returns_full_timeline(shotcut: Shotcut) -> None:
    shotcut.timeline.markers.clear()
    markers = shotcut.find_markers()
    assert len(markers) == 1
    start, end = markers[0]
    assert start == Decimal(0)
    assert end > Decimal(0)


def test_find_markers_odd_count_appends_end(shotcut: Shotcut) -> None:
    from decimal import Decimal
    shotcut.timeline.markers[0] = Marker(index=0, text="a", colour="#f00", time=Decimal(30))
    markers = shotcut.find_markers()
    assert len(markers) == 1
    assert markers[0][0] == Decimal(30)


def test_str_to_timedelta_parses_timestamp() -> None:
    td = str_to_timedelta("00:01:30.500")
    assert td == timedelta(minutes=1, seconds=30, milliseconds=500)


def test_str_to_timedelta_parses_days() -> None:
    td = str_to_timedelta("1:00:00:00.000")
    assert td == timedelta(days=1), f"Got {td}"


def test_str_to_timedelta_empty_string() -> None:
    td = str_to_timedelta("")
    assert td == timedelta(0)


def test_timedelta_to_str_roundtrip() -> None:
    cases = [
        timedelta(hours=1, minutes=30, seconds=15, milliseconds=500),
        timedelta(seconds=0),
        timedelta(hours=26),  # 1 day + 2 hours
        timedelta(milliseconds=999),
    ]
    for td in cases:
        result = str_to_timedelta(timedelta_to_str(td))
        assert abs((result - td).total_seconds()) < 0.001, f"Failed for {td}: got {result}"


def test_pack_bin_fits_songs() -> None:
    songs = [
        Song(id=i, name=f"song{i}", length=timedelta(seconds=30), path=Path(), properties={})
        for i in range(3)
    ]
    placed, remaining = pack_bin(timedelta(minutes=2), songs, timedelta(0), timedelta(5))
    assert len(placed) > 0
    assert remaining >= timedelta(0)


def test_pack_bin_respects_gap() -> None:
    songs = [
        Song(id=i, name=f"song{i}", length=timedelta(seconds=60), path=Path(), properties={})
        for i in range(2)
    ]
    placed, remaining = pack_bin(timedelta(seconds=125), songs, timedelta(seconds=5), timedelta(seconds=5))
    assert len(placed) == 2


def test_shotcut_add_clip_to_track(shotcut: Shotcut) -> None:
    track = shotcut.timeline.main_video
    n_before = len(track.clips)
    shotcut.add_clip_to_track(track, bin_asset_id=0, start=shotcut.timeline.duration, duration=shotcut.framerate)
    assert len(track.clips) == n_before + 1


def test_shotcut_clear_track(shotcut: Shotcut) -> None:
    track = shotcut.timeline.main_video
    shotcut.clear_track(track)
    assert len(track.clips) == 0
    assert len(track.transitions) == 0


def test_shotcut_find_assets_by_path(shotcut: Shotcut) -> None:
    assets = shotcut.find_assets_by_path(Path("/nonexistent"))
    assert assets == []


def test_load_project_roundtrip(tmp_path: Path, shotcut: Shotcut) -> None:
    out = tmp_path / "roundtrip.mlt"
    shotcut.save(out)
    assert out.exists()
    reloaded = Shotcut(out)
    assert len(reloaded._tracks) == len(shotcut._tracks)
    assert reloaded.timeline.duration == shotcut.timeline.duration
    assert len(reloaded.assets) == len(shotcut.assets)


def test_background_music_pipeline(tmp_path: Path, shotcut: Shotcut) -> None:
    unused_id = next(i for i in shotcut.assets if i not in
                     {c.bin_asset_id for c in shotcut.timeline.main_video.clips.values()})
    songs = [
        Song(id=unused_id, name="test", length=timedelta(seconds=2),
             path=Path(), properties={}),
    ]
    track = shotcut.timeline.main_video

    end_time = timedelta(seconds=float(shotcut.timeline.duration))
    markers = [(timedelta(seconds=5), end_time)]
    locations = find_song_locations(track, markers, songs, timedelta(0))
    assert len(locations) > 0

    writable = insert_songs(locations, songs, [], timedelta(0), timedelta(0))
    assert len(writable) > 0

    shotcut.clear_track(track)
    assert len(track.clips) == 0

    for start, song in writable:
        shotcut.add_clip_to_track(
            track, bin_asset_id=song.id,
            start=Decimal(str(start.total_seconds())),
            duration=Decimal(str(song.length.total_seconds())),
            source_in=Decimal(0),
        )
    assert len(track.clips) == len(writable)

    shotcut.add_filter_to_track(
        track, filter_id="filter0",
        length=format_time(shotcut.timeline.duration),
        properties={"mlt_service": "volume", "level": "-3dB"},
    )
    assert len(track.filters) == 1

    out = tmp_path / "bg_music.mlt"
    shotcut.save(out)
    assert out.exists() and out.stat().st_size > 0

    reloaded = Shotcut(out)
    assert reloaded.timeline.duration == shotcut.timeline.duration
    assert len(reloaded.assets) == len(shotcut.assets)


def _make_synthetic_project(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal Shotcut project with known short assets for testing."""
    from xml.etree.ElementTree import Element, ElementTree, indent, SubElement
    import wave
    import struct

    audio_file = tmp_path / "test_audio.wav"
    with wave.open(str(audio_file), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        frames = struct.pack(f"<{44100 * 5}h", *([0] * 44100 * 5))
        wf.writeframes(frames)

    mlt_file = tmp_path / "test.mlt"
    root = Element("mlt", {"title": "Shotcut test", "producer": "main_bin"})
    SubElement(root, "profile", {
        "frame_rate_num": "30", "frame_rate_den": "1",
        "width": "1920", "height": "1080",
        "display_aspect_num": "16", "display_aspect_den": "9",
        "sample_aspect_num": "1", "sample_aspect_den": "1",
        "progressive": "1",
    })
    tractor = SubElement(root, "tractor", {"id": "tractor0", "title": "test", "in": "00:00:00.000", "out": "00:00:10.000"})
    for prop in [("shotcut", "1"), ("shotcut:projectAudioChannels", "2"), ("shotcut:projectFolder", "1")]:
        SubElement(tractor, "property", {"name": prop[0]}).text = prop[1]
    SubElement(tractor, "track", {"producer": "playlist0"})

    consumer = SubElement(root, "consumer", {})
    SubElement(consumer, "property", {"name": "mlt_service"}).text = "sdl2_audio"

    chain = SubElement(root, "chain", {"id": "chain0", "out": "00:00:05.000"})
    for name, val in [("length", "00:00:05.000"), ("resource", str(audio_file)),
                       ("mlt_service", "avformat")]:
        SubElement(chain, "property", {"name": name}).text = val

    main_bin = SubElement(root, "playlist", {"id": "main_bin"})
    for name in ("shotcut:projectAudioChannels", "shotcut:projectFolder", "shotcut:processingMode", "shotcut:skipConvert"):
        SubElement(main_bin, "property", {"name": name}).text = "1"

    playlist = SubElement(root, "playlist", {"id": "playlist0"})
    SubElement(playlist, "property", {"name": "shotcut:name"}).text = "V1"
    SubElement(playlist, "blank", {"length": "00:00:02.000"})
    SubElement(playlist, "entry", {"producer": "chain0", "in": "00:00:00.000", "out": "00:00:03.000"})
    SubElement(playlist, "blank", {"length": "00:00:02.000"})
    SubElement(playlist, "entry", {"producer": "chain0", "in": "00:00:00.000", "out": "00:00:03.000"})

    props = SubElement(tractor, "properties", {"name": "shotcut:markers"})
    SubElement(props, "property", {"name": "0"}).text = json.dumps({"start": "00:00:02.000", "text": "gap", "color": "#ff0000"})
    SubElement(props, "property", {"name": "1"}).text = json.dumps({"start": "00:00:04.000", "text": "end", "color": "#00ff00"})

    indent(root)
    tree = ElementTree(root)
    tree.write(mlt_file, encoding="utf-8", xml_declaration=True)
    return mlt_file, audio_file


def test_background_music_entrypoint_returns_0(tmp_path: Path) -> None:
    import json
    mlt_file, audio_file = _make_synthetic_project(tmp_path)
    args = Namespace(
        project=mlt_file,
        project_path=None,
        music=[audio_file.parent],
        track_name="BG Music",
        min_gap=0.0,
        max_gap=0.0,
        gain="-3",
        dry_run=False,
    )
    result = background_music(args)
    assert result == 0, f"background_music returned {result}"
    assert mlt_file.exists()


def test_background_music_entrypoint_dry_run_does_not_save(tmp_path: Path) -> None:
    import json
    mlt_file, audio_file = _make_synthetic_project(tmp_path)
    old_mtime = mlt_file.stat().st_mtime

    args = Namespace(
        project=mlt_file,
        project_path=None,
        music=[audio_file.parent],
        track_name="BG Music",
        min_gap=0.0,
        max_gap=0.0,
        gain="-3",
        dry_run=True,
    )
    result = background_music(args)
    assert result == 0
    assert mlt_file.stat().st_mtime == old_mtime, "File was modified despite dry_run"
