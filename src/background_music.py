from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from logging import Logger, getLogger
from pathlib import Path
from random import shuffle
from typing import Optional

from .shotcut import Shotcut, Track, find_project, find_latest_project, format_time

LOG = getLogger("background-music")


@dataclass
class Song:
    id: int
    name: str
    length: timedelta
    path: Path
    properties: dict[str, str]

    def __repr__(self):
        return f"{self.name} ({self.length})"


def find_songs(shotcut: Shotcut, music: list[Path]) -> list[Song]:
    songs = []
    for idx, asset in shotcut.assets.items():
        if any(asset.path.is_relative_to(mpath) for mpath in music):
            songs.append(
                Song(
                    id=idx,
                    name=asset.path.stem,
                    length=timedelta(seconds=float(asset.duration)),
                    path=asset.path,
                    properties={},
                )
            )
    return songs


def _debug_locations(log: Logger, locs: list[tuple[timedelta, timedelta]]) -> None:
    for s, e in locs:
        log.debug(f"- {s} -> {e} ({e - s})")


def _debug_songs(
    log: Logger, songs: list[tuple[timedelta, Song]], prefix: str = "Placed"
) -> None:
    log.info(f"{prefix} {len(songs)} songs".capitalize())
    for start, song in songs:
        log.debug(f"- {start} {song}")


def find_existing_songs(
    track: Track, songs: list[Song]
) -> list[Song]:
    song_map = {s.id: s for s in songs}
    existing: list[Song] = []
    for clip in track.clips.values():
        if clip.bin_asset_id in song_map:
            existing.append(song_map[clip.bin_asset_id])
    return existing


def find_song_locations(
    track: Track,
    markers: list[tuple[timedelta, timedelta]],
    songs: list[Song],
    padding: timedelta,
) -> list[tuple[timedelta, timedelta]]:
    if not songs:
        return []
    shortest = min(s.length for s in songs)
    song_map = {s.id: s for s in songs}

    timeline: list[tuple[timedelta, Song]] = []
    for clip in track.sorted_clips:
        if clip.bin_asset_id in song_map:
            timeline.append(
                (timedelta(seconds=float(clip.start)), song_map[clip.bin_asset_id])
            )

    valid_locations: list[tuple[timedelta, timedelta]] = []
    for s, e in markers:
        bins = [(s, e)]

        for song_start, song in timeline:
            start = song_start - padding
            end = song_start + song.length + padding

            new_bins = []
            for bin_start, bin_end in bins:
                if bin_end <= start or bin_start >= end:
                    new_bins.append((bin_start, bin_end))
                else:
                    if bin_start <= start:
                        new_bins.append((bin_start, start))
                    if bin_end >= end:
                        new_bins.append((end, bin_end))
            bins = new_bins

        valid_locations.extend(bins)

    log = LOG.getChild("bin-finder")
    log.debug(f"{len(valid_locations)} potential song bins:")
    _debug_locations(log, valid_locations)

    log.debug(f"Removing any bins smaller than {shortest}")
    valid_locations = [(s, e) for s, e in valid_locations if (e - s) >= shortest]

    return valid_locations


def pack_bin(
    size: timedelta, songs: list[Song], min_gap: timedelta, max_gap: timedelta
) -> tuple[list[Song], timedelta]:
    placed: list[Song] = []
    total_min, total_max = timedelta(0), timedelta(0)

    for _ in range(3):
        shuffle(songs)
        for song in songs:
            if song in placed:
                continue

            song_length = song.length
            if total_min + song_length <= size:
                placed.append(song)
                total_min += song_length + min_gap
                total_max += song_length + max_gap

            if total_max >= size:
                return placed, timedelta(0)

    return placed, size - total_min


def insert_songs(
    locations: list[tuple[timedelta, timedelta]],
    songs: list[Song],
    used_songs: list[Song],
    min_gap: timedelta,
    max_gap: timedelta,
) -> list[tuple[timedelta, Song]]:
    remaining_songs = [s for s in songs if s not in used_songs]
    log = LOG.getChild("song-filler")

    songs_bins: list[tuple[timedelta, timedelta, list[Song]]] = []

    for start, end in sorted(locations, key=lambda location: location[1] - location[0]):
        trial_bins = sorted(
            [
                pack_bin(end - start, remaining_songs, min_gap, max_gap)
                for _ in range(5)
            ],
            key=lambda trial_bin: trial_bin[1],
        )

        this_bin, _ = trial_bins[0]
        if this_bin:
            log.debug(f"Adding to bin: {start}, {end} ({end - start}):")
            log.debug("- " + ", ".join([str(s) for s in this_bin]))
            songs_bins.append((start, end, this_bin))

            used_songs.extend(this_bin)
            remaining_songs = [s for s in remaining_songs if s not in used_songs]
        else:
            log.debug(f"No valid songs could fill: {start}, {end} ({end - start}):")

    if not songs_bins:
        return []

    song_order: list[tuple[timedelta, Song]] = []

    for s, e, entries in songs_bins:
        this_order: list[tuple[timedelta, Song]] = []
        song_length = timedelta(0)
        for song in entries:
            song_length += song.length

        gap_per_song = (e - s - song_length) / (1 + len(entries))
        shuffle(entries)
        now = s + gap_per_song
        for song in entries:
            this_order.append((now, song))
            now += song.length + gap_per_song

        song_order.extend(this_order)

    return sorted(song_order, key=lambda s: s[0])


def background_music(args: Namespace) -> int:
    log = LOG.getChild("music")
    if not args.music:
        log.error(
            "You must specify a music path to locate songs within the project playlist"
        )
        return 1

    assert args.min_gap >= 0, "Cannot specify a negative minimum gap"
    assert (
        args.max_gap >= args.min_gap
    ), "The maximum gap must be larger than the minimum gap"

    project = (
        find_project(args.project)
        if args.project
        else find_latest_project(args.project_path)
    )
    if not project:
        log.error(f"Could not find project file at {args.project or args.project_path}")
        return 1
    log.debug(f"Using {project} as the shotcut project")

    shotcut = Shotcut(project)

    songs = find_songs(shotcut, args.music)
    if not songs:
        log.error("Could not find any valid songs in the project")
        log.info("Import any background music you want to use into the project")
        return 1
    log.info(f"found {len(songs)} songs")
    log.debug(songs)

    markers_raw = shotcut.find_markers()
    markers = [
        (timedelta(seconds=float(s)), timedelta(seconds=float(e)))
        for s, e in markers_raw
    ]
    if not markers:
        log.error("Could not find any valid positions to fill with songs")
        return 1
    log.info(f"found {len(markers)} locations for songs to be placed")
    _debug_locations(log, markers)

    track = shotcut.get_or_create_track(args.track_name, kind="video")
    track.mix = True
    track.blend = True
    log.debug(f"Using track '{track.name}' (index {track.index})")

    song_locations = find_song_locations(
        track, markers, songs, timedelta(seconds=args.min_gap)
    )
    if not song_locations:
        log.error("Could not find any valid positions to insert songs")
        return 1
    log.info(f"found {len(song_locations)} valid locations for songs to be placed")
    _debug_locations(log, song_locations)

    used_songs = find_existing_songs(track, songs)
    if used_songs:
        log.debug(
            f"Track already contains {len(used_songs)} songs which will not be selected"
        )
        for s in used_songs:
            log.debug(f"- {s}")

    writable_songs = insert_songs(
        song_locations,
        songs,
        used_songs,
        timedelta(seconds=args.min_gap),
        timedelta(seconds=args.max_gap),
    )
    if not writable_songs:
        log.error("We could not insert any songs into the provided positions")
        return 1
    _debug_songs(log, writable_songs)

    shotcut.clear_track(track)

    for start, song in writable_songs:
        shotcut.add_clip_to_track(
            track,
            bin_asset_id=song.id,
            start=Decimal(str(start.total_seconds())),
            duration=Decimal(str(song.length.total_seconds())),
            source_in=Decimal(0),
        )

    shotcut.add_filter_to_track(
        track,
        filter_id="filter0",
        length=format_time(shotcut.timeline.duration),
        properties={
            "window": "75",
            "max_gain": "20dB",
            "level": str(args.gain),
            "channel_mask": "-1",
            "mlt_service": "volume",
            "filter": "audioGain",
        },
    )

    shotcut.clear_markers()

    if not args.dry_run:
        shotcut.save()
    else:
        log.info(
            "Project on disk has not been modified, run"
            " without `--dry-run` set to make changes."
        )

    return 0
