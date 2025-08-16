import re
import xml.etree.ElementTree as ET
from argparse import Namespace
from dataclasses import dataclass
from datetime import timedelta
from logging import Logger, getLogger
from pathlib import Path
from random import shuffle
from xml.etree.ElementTree import Element, ElementTree

LOG = getLogger("background-music")

ISO_DATE = re.compile(r"\d{4}\-\d{2}\-\d{2}T\d{2}\-\d{2}\-\d{2}")
TIMESTAMP = re.compile(r"(\d+:)?(\d{2}):(\d{2}):(\d{2})\.(\d{3})")


@dataclass
class Song:
    id: str
    name: str
    length: timedelta
    path: Path
    properties: dict[str, str]

    def __repr__(self):
        """Represent a Song object as a string of 'name (length)'."""
        return f"{self.name} ({self.length})"


def as_time(time_string: str) -> timedelta:
    """Convert a (dd:)?hh:mm:ss.mmm string to a timedelta."""
    if tstring := TIMESTAMP.search(time_string):
        days, hours, minutes, seconds, millis = tstring.groups()
        return timedelta(
            days=int(days or "0"),
            hours=int(hours),
            minutes=int(minutes),
            seconds=int(seconds),
            milliseconds=int(millis),
        )
    return timedelta(0)


def from_time(time_time: timedelta) -> str:
    """Convert a timedelta to a (dd:)?hh:mm:ss.mmm string."""
    h, r = divmod(time_time.seconds, 3600)
    m, s = divmod(r, 60)
    time_string = f"{h:0>2}:{m:0>2}:{s:0>2}.{time_time.microseconds // 1000}"
    if time_time.days > 0:
        time_string = f"{time_time.days // 86400}:{time_string}"
    return time_string


def find_project(path: Path) -> Path | None:
    """Return the project file if passed directly.

    Otherwise, if given a directory, search for all .mlt files
    and filter out backup versions.
    """
    if path.is_dir():
        if files := list(path.glob("*.mlt")):
            return [x for x in files if not ISO_DATE.search(x.stem)][0]

    elif path.suffix == ".mlt":
        return path

    return None


def _get_properties(element: Element) -> dict[str, str]:
    """Return all 'property' children by name for an element."""
    return {
        name: (p.text or "")
        for p in element.findall("property")
        if (name := p.get("name"))
    }


def find_songs(music: Path, root: Element) -> list[Song]:
    """Find a reference to all valid songs in the project."""
    songs = []
    for item in root.findall("chain"):
        properties = _get_properties(item)
        path = Path(properties["resource"])
        if (
            (path.is_relative_to(music))
            and (id := item.get("id"))
            and (out := item.get("out"))
        ):
            songs.append(
                Song(
                    id=id,
                    name=path.stem,
                    length=as_time(out),
                    path=path,
                    properties=properties,
                )
            )

    return songs


def _find_main(root: Element) -> Element:
    """Return the objet that represents the project meta."""
    title = root.get("title")
    for item in root.findall("tractor"):
        if item.get("title") == title:
            return item
    raise Exception("Could not locate the main metadata object")


def find_markers(root: Element) -> list[tuple[timedelta, timedelta]]:
    """Return a list of markers attached to the project."""
    if main_track := _find_main(root):
        in_time = as_time(main_track.get("in", "00:00:00.000"))
        out_time = as_time(main_track.get("out", "00:00:00.000"))
        markers = []

        if marker_nodes := main_track.find("properties[@name='shotcut:markers']"):
            for node in marker_nodes.findall("properties"):
                if start := _get_properties(node).get("start"):
                    markers.append(as_time(start))

        # if we have an odd number of markers, append the final time too
        if len(markers) % 2:
            markers.append(out_time)

        # if we had no markers, return the start and end
        if not markers:
            return sorted([(in_time, out_time)])

        _markers = sorted(markers)
        return list(zip(_markers[::2], _markers[1::2]))

    return []


def _node_id(item: Element) -> int:
    if this_id := re.search(r"\d+", item.get("id", "")):
        return int(this_id.group())
    return 0


def _find_filters(root: Element) -> list[Element]:
    # we only want consecutive filters, as we can insert afterwards
    filters = sorted(root.findall(".//filter"), key=lambda item: _node_id(item))
    for x, filt in enumerate(filters):
        if x != _node_id(filt):
            return filters[:x]
    return filters


def _construct_gain_filer(length: str, gain: int = -20) -> Element:
    filter_elem = ET.Element("filter", {"id": "filter", "out": length})

    window = ET.SubElement(filter_elem, "property", {"name": "window"})
    max_gain = ET.SubElement(filter_elem, "property", {"name": "max_gain"})
    level = ET.SubElement(filter_elem, "property", {"name": "level"})
    channel_mask = ET.SubElement(filter_elem, "property", {"name": "channel_mask"})
    mlt_service = ET.SubElement(filter_elem, "property", {"name": "mlt_service"})
    filtr = ET.SubElement(filter_elem, "property", {"name": "filter"})

    window.text = "75"
    max_gain.text = "20dB"
    level.text = str(gain)
    channel_mask.text = "-1"
    mlt_service.text = "volume"
    filtr.text = "audioGain"

    return filter_elem


def get_or_create_song_track(root: Element, name: str) -> Element:
    """Return the chosen track, or create new if none found."""
    max_id = 0

    # find the preexisting
    for track in root.findall("playlist"):
        max_id = max(max_id, _node_id(track))

        props = _get_properties(track)
        this_name = props.get("shotcut:name")
        if this_name == name:
            return track

    # construct a new playlist object
    pid = f"playlist{max_id + 1}"
    playlist = ET.Element("playlist", {"id": pid})
    video_elem = ET.SubElement(playlist, "property", {"name": "shotcut:video"})
    name_elem = ET.SubElement(playlist, "property", {"name": "shotcut:name"})
    video_elem.text = "1"
    name_elem.text = name

    # shenanignas to insert the playlist object in
    # the right place (just before the tractor)
    main = _find_main(root)
    for i, child in enumerate(list(root)):
        if child != main:
            continue
        root.insert(i, playlist)
        break

    # and ensure the tractor now contains a reference
    # to the playlist
    for i, prop in enumerate(list(main)):
        if prop.tag == "track":
            if prop.get("producer") == f"playlist{max_id}":
                main.insert(i + 1, ET.Element("track", {"producer": pid}))
                break

    return playlist


def _get_song_timeline(
    track: Element, songs: list[Song]
) -> list[tuple[timedelta, Song]]:
    timeline = []
    now = timedelta(0)
    song_map = {s.id: s for s in songs}

    for item in track.iter():
        match item.tag:
            case "blank":
                now += as_time(item.get("length", "00:00:00.000"))
            case "entry":
                length = as_time(item.get("out", "00:00:00.000"))
                timeline.append((now, song_map[item.get("producer", "")]))
                now += length

    return timeline


def _debug_locations(log: Logger, locs: list[tuple[timedelta, timedelta]]):
    for s, e in locs:
        log.debug(f"- {s} -> {e} ({e - s})")


def find_song_locations(
    track: Element,
    markers: list[tuple[timedelta, timedelta]],
    songs: list[Song],
    padding: timedelta,
) -> list[tuple[timedelta, timedelta]]:
    """Construct a list of all valid song positions."""
    shortest = min([s.length for s in songs])

    timeline = _get_song_timeline(track, songs)

    valid_locations: list[tuple[timedelta, timedelta]] = []
    for s, e in markers:
        bins = [(s, e)]

        # check for any pre-existing song collisions
        for song_start, song in timeline:
            # respect the minimum padding requirements
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


def find_existing_songs(track: Element, songs: list[Song]) -> list[Song]:
    """Return a list of all the songs already on a track."""
    song_map = {s.id: s for s in songs}
    return [song_map[item.get("producer", "")] for item in track.findall("entry")]


def pack_bin(
    size: timedelta, songs: list[Song], min_gap: timedelta, max_gap: timedelta
) -> tuple[list[Song], timedelta]:
    """Place songs inside the provided bin."""
    placed = []
    total_min, total_max = timedelta(0), timedelta(0)

    # allow up to 3 passes through the songs array to fit them into bins
    for _ in range(3):
        shuffle(songs)
        for song in songs:
            # don't duplicate
            if song in placed:
                continue

            # the song will fit in the bin
            song_length = song.length
            if total_min + song_length <= size:
                placed.append(song)
                total_min += song_length + min_gap
                total_max += song_length + max_gap

            # the bin is slightly overfilled, we've done a great jon
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
    """Insert songs onto a track, respecting all bins."""
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

        # select the bin with the lowest difference to the perfect length
        this_bin, _ = trial_bins[0]
        if this_bin:
            log.debug(f"Adding to bin: {start}, {end} ({end - start}):")
            log.debug("- " + ", ".join([str(s) for s in this_bin]))
            songs_bins.append((start, end, this_bin))

            used_songs.extend(this_bin)
            remaining_songs = [s for s in remaining_songs if s not in used_songs]
        else:
            log.debug(f"No valid songs could fill: {start}, {end} ({end - start}):")

    #  exit early
    if not songs_bins:
        return []

    # generate a list of all song positions
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


def delete_markers(root: Element) -> None:
    """Delete all markers on the main element."""
    if main_track := _find_main(root):
        if marker_nodes := main_track.find("properties[@name='shotcut:markers']"):
            main_track.remove(marker_nodes)


def write_songs_to_track(
    track: Element, songs: list[tuple[timedelta, Song]], all_songs: list[Song]
) -> None:
    """Add songs from the list to the track element."""
    used_songs = _get_song_timeline(track, all_songs)
    used_songs.extend(songs)

    sorted_songs = sorted(used_songs, key=lambda s: s[0])

    # clear the old songs list
    for blank in track.findall("blank"):
        track.remove(blank)
    for entry in track.findall("entry"):
        track.remove(entry)

    # insert the new one
    now = timedelta(0)
    for start, song in sorted_songs:
        blank = ET.Element("blank", {"length": from_time(start - now)})
        entry = ET.Element(
            "entry",
            {"producer": song.id, "in": "00:00:00.000", "out": from_time(song.length)},
        )
        now = start + song.length
        track.extend((blank, entry))

    # and move the filter
    if filtr := track.find("filter"):
        track.remove(filtr)
        track.append(filtr)


def write_tree(tree: ElementTree[Element], project: Path) -> None:
    """Save the element tree to disk."""
    ET.indent(tree)
    tree.write(project, encoding="utf-8", xml_declaration=True)


def background_music(args: Namespace) -> int:
    """Entrypoint for background music automation."""
    log = LOG.getChild("music")

    # Fetch the project file and parse the XML
    project = find_project(args.project)
    if not project:
        log.error(f"Could not find project file at {args.project}")
        return 1
    log.debug(f"Using {project} as the shotcut project")

    tree = ET.parse(project)
    root = tree.getroot()
    main_track = _find_main(root)

    # Fetch valid songs
    songs = find_songs(args.music, root)
    if not songs:
        log.error("Could not find any valid songs in the project")
        return 1
    log.info(f"found {len(songs)} songs")
    log.debug(songs)

    # Fetch markers
    markers = find_markers(root)
    if not songs:
        log.error("Could not find any valid positions to fill with songs")
        return 1
    log.info(f"found {len(markers)} locations for songs to be placed")
    _debug_locations(log, markers)

    # Fetch / create video track
    song_track = get_or_create_song_track(root, args.track_name)

    # Write or modify the filter on the track
    gain_filter = _construct_gain_filer(main_track.get("out", "00:00:00.000"))
    if existing := song_track.find("filter"):
        song_track.remove(existing)
    gain_filter.set(
        "id",
        (
            "filter" + (str(_node_id(filters) + 1))
            if (filters := _find_filters(root)[-1])
            else "0"
        ),
    )
    song_track.append(gain_filter)

    # Determine valid song locations
    song_locations = find_song_locations(
        song_track, markers, songs, timedelta(seconds=args.min_gap)
    )
    if not song_locations:
        log.error("Could not find any valid positions to insert songs")
        return 1
    log.info(f"found {len(song_locations)} valid locations for songs to be placed")
    _debug_locations(log, song_locations)

    # Determine any songs already in use
    used_songs = find_existing_songs(song_track, songs)
    if used_songs:
        log.debug(
            f"Track already contains {len(used_songs)} songs which will not be selected"
        )
        for s in used_songs:
            log.debug(f"- {s}")

    # Populate track
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
    log.info(f"Placed {len(writable_songs)} songs into the provided positions")
    for start, song in writable_songs:
        log.debug(f"- {start} {song}")

    # Delete the markers:
    delete_markers(root)

    # Write back to file
    write_songs_to_track(song_track, writable_songs, songs)
    write_tree(tree, project)

    return 0
