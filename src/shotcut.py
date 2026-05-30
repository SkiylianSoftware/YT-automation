from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum, auto
from pathlib import Path
from re import compile as re_compile, search
from signal import SIGALRM, alarm, signal
from typing import Any, Literal, Optional
from xml.etree.ElementTree import Element, ElementTree, indent, parse

from .shotcut_transitions import Transition


def parse_time(t: str, frame_rate: Decimal | None = None) -> Decimal:
    parts = t.split(":")
    if len(parts) == 4:
        h, m, s, f = parts
        fr = frame_rate or Decimal(60)
        return Decimal(h) * 3600 + Decimal(m) * 60 + Decimal(s) + Decimal(f) / fr
    if len(parts) == 1:
        return Decimal(t)
    h, m, s = parts
    return Decimal(h) * 3600 + Decimal(m) * 60 + Decimal(s)


def format_time(seconds: Decimal) -> str:
    h, residue = divmod(seconds, 3600)
    m, s = divmod(residue, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}"


def zero_time() -> str:
    return format_time(Decimal(0))


def files_in_dir(path: Path, extension: str = ".mlt") -> list[Path]:
    return list(path.glob(f"**/*{extension}"))


def force_hex(text: str, default: str = "#008000") -> str:
    if found := search(r"#[0-9A-F]{6}", text.upper()):
        return found.group()
    return default


def iso_file(path: Path) -> bool:
    return search(r"\d{4}\-\d{2}\-\d{2}T\d{2}\-\d{2}\-\d{2}", path.stem) is not None


def find_project(path: Path) -> Path | None:
    if path.is_dir():
        if files := files_in_dir(path):
            return [x for x in files if not iso_file(x)][0]
    elif path.suffix == ".mlt":
        return path
    return None


def find_latest_project(path: Path, timeout: int = 10) -> Path | None:
    """Return the latest modified project file."""
    if not path.is_dir():
        return None

    projects = sorted(
        files_in_dir(path),
        key=lambda p: datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc),
        reverse=True,
    )

    class Expired(Exception):
        pass

    def _time_out(signum, frame):
        raise Expired

    print(
        f"Showing files in {path.stem} from newest to oldest",
        f"You will have {timeout} seconds to make a selection",
        sep="\n",
    )
    signal(SIGALRM, _time_out)
    for project in projects:
        alarm(timeout)
        try:
            ans = ""
            while ans not in ("y", "n"):
                ans = input(f"Use {project.stem} (y/n\n>> ").strip().lower()
            alarm(0)
            if ans == "y":
                return project
        except Expired:
            return project
    return None


def timedelta_to_str(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    d, r = divmod(total_seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    millis = td.microseconds // 1000
    if d:
        return f"{d}:{h:0>2}:{m:0>2}:{s:0>2}.{millis:03d}"
    return f"{h:0>2}:{m:0>2}:{s:0>2}.{millis:03d}"


def str_to_timedelta(time_string: str) -> timedelta:
    TIMESTAMP = re_compile(r"(?:(\d+):)?(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
    if tstring := TIMESTAMP.search(time_string):
        days, hours, minutes, seconds, millis = tstring.groups()
        return timedelta(
            days=int(days) if days else 0,
            hours=int(hours),
            minutes=int(minutes),
            seconds=int(seconds),
            milliseconds=int(millis),
        )
    return timedelta(0)


class CollisionStrategy(Enum):
    REJECT = auto()  # Don't allow clips to collide
    MOVE = auto()  # Any clips that collide with the moved will be shunted back in time
    SPLIT = auto()
    # Any clips that collide with the moved will be split, reserving the moved clip
    REPLACE = auto()  # Any clips that collide with the moved will be deleted


class TransitionStrategy(Enum):
    KEEP = auto()  # don't move transitions attached to the moving clip
    GROW_OR_KEEP = (
        auto()
    )  # increase the transition duration if the clip is moved but still adjacent, else KEEP
    GROW_OR_MOVE = (
        auto()
    )  # increase the transition duration if the clip is moved but still adjacent, else MOVE
    MOVE = auto()  # Move any transitions attached to the moving clip
    GLUE = (
        auto()
    )  # Move the transitions, then any other clips attached, until everything has shifted.


@dataclass
class BinAsset:
    index: int
    path: Path
    duration: Decimal
    mlt_service: str = "avformat"
    is_producer: bool = False
    attrib: dict[str, str] = field(default_factory=dict)
    properties: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"asset: {self.path}"

    def __str__(self) -> str:
        return self.__repr__()

    @property
    def duration_string(self) -> str:
        return format_time(self.duration)

@dataclass
class FilterableObject:
    pass

@dataclass
class TimelineClip(FilterableObject):
    index: int
    bin_asset_id: int
    track: int
    start: Decimal
    duration: Decimal
    source_in: Decimal
    source_out: Decimal
    filters: list[Element] = field(default_factory=list)

    @property
    def chain_id(self) -> str:
        return f"chain{self.index}"

    def __repr__(self) -> str:
        return f"clip: asset {self.bin_asset_id} at {self.start_string} ({self.duration_string})"

    def __str__(self) -> str:
        return self.__repr__()

    @property
    def end(self) -> Decimal:
        return self.start + self.duration

    @property
    def start_string(self) -> str:
        return format_time(self.start)

    @property
    def end_string(self) -> str:
        return format_time(self.end)

    @property
    def duration_string(self) -> str:
        return format_time(self.duration)

    @property
    def source_in_string(self) -> str:
        return format_time(self.source_in)

    @property
    def source_out_string(self) -> str:
        return format_time(self.source_out)


@dataclass
class TimelineTransition(FilterableObject):
    start: Decimal
    track: int
    transition: Transition

    def __repr__(self) -> str:
        return f"transition: {self.transition.video_transition.__class__.__name__}"

    def __str__(self) -> str:
        return self.__repr__()

    @property
    def end(self) -> Decimal:
        return self.start + self.duration

    @property
    def index(self) -> int:
        return self.transition.index

    @property
    def duration(self) -> Decimal:
        return self.transition.duration

    @property
    def left_clip(self) -> int:
        return self.transition.clip_start

    @property
    def right_clip(self) -> int:
        return self.transition.clip_end

    @index.setter
    def index(self, idx: int) -> None:
        self.transition.index = idx

    @duration.setter
    def duration(self, value: Decimal) -> None:
        self.transition.duration = value

    @left_clip.setter
    def left_clip(self, clip: int) -> None:
        self.transition.clip_start = clip

    @right_clip.setter
    def right_clip(self, clip: int) -> None:
        self.transition.clip_end = clip

    @property
    def end(self) -> Decimal:
        return self.start + self.duration

    @property
    def start_string(self) -> str:
        return format_time(self.start)

    @property
    def end_string(self) -> str:
        return format_time(self.end)

    @property
    def duration_string(self) -> str:
        return format_time(self.duration)


@dataclass
class Track(FilterableObject):
    index: int
    name: str
    kind: Literal["video", "audio"]
    clips: dict[int, TimelineClip]
    transitions: dict[int, TimelineTransition]
    blend: bool = False
    mix: bool = False
    filters: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    transition_only_clips: dict[int, TimelineClip] = field(default_factory=dict)

    @property
    def sorted_clips(self) -> list[TimelineClip]:
        return sorted(self.clips.values(), key=lambda c: c.start)

    @property
    def sorted_transitions(self) -> list[TimelineTransition]:
        return sorted(self.transitions.values(), key=lambda c: c.start)

    @property
    def sorted_all(self) -> list[TimelineClip | TimelineTransition]:
        return sorted(
            list(self.clips.values()) + list(self.transitions.values()),
            key=lambda c: c.start,
        )

    @property
    def duration(self) -> Decimal:
        t_max = max(
            list(transition.end for transition in self.transitions.values())
            + [Decimal(0)]
        )
        c_max = max(list(clip.end for clip in self.clips.values()) + [Decimal(0)])
        return max(t_max, c_max)

    def remove(self, obj: TimelineClip | TimelineTransition) -> None:
        if isinstance(obj, TimelineClip):
            self.clips.pop(obj.index)
        elif isinstance(obj, TimelineTransition):
            self.transitions.pop(obj.index)

    @property
    def duration_string(self) -> str:
        return format_time(self.duration)


@dataclass
class Marker:
    index: int
    text: str
    time: Decimal
    colour: str

    @property
    def time_string(self) -> str:
        return format_time(self.time)


@dataclass
class Timeline:
    tracks: dict[int, Track]
    markers: dict[int, Marker]

    @property
    def main_video(self) -> Track:
        for track in self.tracks.values():
            if track.kind == "video":
                return track
        video = Track(0, "V1", "video", {}, {})
        self.bump_tracks(0)
        self.tracks[0] = video
        return video

    @property
    def main_audio(self) -> Track:
        for track in self.tracks.values():
            if track.kind == "audio":
                return track
        audio = Track(1, "A1", "audio", {}, {})
        self.bump_tracks(1)
        self.tracks[1] = audio
        return audio

    def track_by_name(self, name: str = "V1") -> Track | None:
        for track in self.tracks.values():
            if track.name == name:
                return track
        return None

    @property
    def duration(self) -> Decimal:
        return max(track.duration for track in self.tracks.values())

    @property
    def duration_string(self) -> str:
        return format_time(self.duration)

    @property
    def sorted_markers(self) -> list[Marker]:
        return sorted(self.markers.values(), key=lambda m: m.time)

    def bump_tracks(self, idx_to_clear: int = 0) -> None:
        remap: dict[int, int] = {}
        allowed = [x for x in range(len(self.tracks.keys()) + 1) if x != idx_to_clear]
        tracks: dict[int, Track] = {}
        for x, track in zip(
            allowed, sorted(self.tracks.values(), key=lambda x: x.index)
        ):
            remap[track.index] = x
        for old, new in remap.items():
            old_track = self.tracks[old]
            clips = {}
            transitions = {}
            tocs = {}
            for clip in old_track.clips.values():
                clip.track = new
                clips[clip.index] = clip
            for transition in old_track.transitions.values():
                transition.track = new
                transitions[transition.index] = transition
            for t_o_c in old_track.transition_only_clips.values():
                t_o_c.track = new
                tocs[t_o_c.index] = t_o_c
            old_track.clips = clips
            old_track.transitions = transitions
            old_track.transition_only_clips = tocs
            old_track.index = new
            tracks[new] = old_track
        self.tracks = tracks


class Shotcut:
    assets: dict[int, BinAsset]
    timeline: Timeline

    def __init__(self, mlt_path: Path):
        assert mlt_path.suffix == ".mlt", f"Invalid file extension {mlt_path.suffix}"
        self.path = mlt_path

        tree = parse(self.path)
        assert tree is not None, f"could not read file {mlt_path}"

        root = tree.getroot()
        assert root is not None, f"Missing root element in {mlt_path}"
        assert root.attrib["title"].startswith("Shotcut"), "Not a shotcut file"
        self.details = root.attrib

        profile = root.find("profile")
        assert profile is not None, "Invalid shotcut file"
        self.profile = profile.attrib

        self._read_bin(root)
        self._read_timeline(root)

    @property
    def framerate(self) -> int:
        return int(self.profile["frame_rate_num"])

    @property
    def height(self) -> int:
        return int(self.profile["height"])

    @property
    def width(self) -> int:
        return int(self.profile["width"])

    def _all_objects(self, root: Element, object_name: str) -> dict[int, Element]:
        obj_map: dict[int, Element] = {}
        for obj in root.findall(object_name):
            if this_id := search(r"\d+", obj.get("id", "")):
                idx = int(this_id.group())
                if idx not in obj_map:
                    obj_map[idx] = obj
        return obj_map

    def _properties(self, elem: Element) -> dict[str, str]:
        return {
            prop.attrib["name"]: prop.text or "" for prop in elem.findall("property")
        }

    def _find_element(self, root: Element, name: str) -> Element | None:
        """Find a chain or producer element by its full ID."""
        tag = name.rstrip("0123456789")
        return root.find(f"{tag}[@id='{name}']")

    def _read_bin(self, root: Element) -> None:
        assets: dict[int, BinAsset] = {}

        for playlist in root.findall("playlist"):
            if playlist.get("id") == self.details["producer"]:
                bin_playlist = playlist
                break
        else:
            raise Exception("Could not find main bin")

        for entry in bin_playlist.findall("entry"):
            producer_name = entry.attrib["producer"]
            elem = self._find_element(root, producer_name)
            if elem is None:
                continue

            properties = self._properties(elem)
            idx = int(search(r"\d+", producer_name).group())

            assets[idx] = BinAsset(
                index=idx,
                path=Path(properties["resource"]),
                duration=parse_time(properties["length"]),
                mlt_service=properties["mlt_service"].removesuffix("-novalidate"),
                is_producer=(elem.tag == "producer"),
                attrib=dict(elem.attrib),
                properties=properties,
            )

        # Index chain and non-timewarp producer elements not in main_bin
        for tag in ("chain", "producer"):
            for elem in root.findall(tag):
                elem_id = elem.get("id", "")
                if match := search(r"\d+", elem_id):
                    idx = int(match.group())
                    props = self._properties(elem)
                    is_timewarp = props.get("mlt_service", "") == "timewarp"
                    if tag == "chain" and idx not in assets:
                        assets[idx] = BinAsset(
                            index=idx,
                            path=Path(props["resource"]),
                            duration=parse_time(props.get("length", "00:00:00.000")),
                            mlt_service=props["mlt_service"].removesuffix("-novalidate"),
                            attrib=dict(elem.attrib),
                            properties=props,
                        )
                    elif tag == "producer" and not is_timewarp:
                        assets[idx] = BinAsset(
                            index=idx,
                            path=Path(props["resource"]),
                            duration=parse_time(props.get("length", "00:00:00.000")),
                            mlt_service=props.get("mlt_service", "avformat").removesuffix("-novalidate"),
                            is_producer=True,
                            attrib=dict(elem.attrib),
                            properties=props,
                        )

        self.assets = assets

    def _find_tractor(self, root: Element) -> Element:
        tractors = root.findall("tractor")
        if not tractors:
            playlist_id = self.details.get("producer", "playlist0")
            tractor = Element("tractor", {"id": "tractor0", "title": self.details.get("title", "")})
            tractor.append(Element("track", {"producer": playlist_id}))
            root.append(tractor)
            return tractor

        for item in tractors:
            if item.get("title") == self.details["title"]:
                return item
        return tractors[0]

    def _read_timeline(self, root: Element) -> None:
        tracks: dict[int, Track] = {}
        markers: dict[int, Marker] = {}

        main = self._find_tractor(root)

        file_tracks = main.findall("track")
        file_playlists = self._all_objects(root, "playlist")
        main_blending_transitions = main.findall("transition")

        blends: dict[str, bool] = {}

        for transition in main_blending_transitions:
            prop = self._properties(transition)
            if prop["mlt_service"] == "frei0r.cairoblend":
                blends[prop["b_track"]] = True

        if (marker_nodes := main.find("properties[@name='shotcut:markers']")) is not None:
            for marker in marker_nodes.findall("properties"):
                this_prop = self._properties(marker)
                idx = int(marker.attrib["name"])
                markers[idx] = Marker(
                    index=idx,
                    text=this_prop["text"],
                    time=parse_time(this_prop["start"], self.framerate),
                    colour=force_hex(this_prop["color"]),
                )

        for track_idx, track in enumerate(file_tracks):
            this_producer = track.attrib["producer"]
            if this_producer.startswith("playlist"):
                idx = int(this_producer.removeprefix("playlist"))
                this_playlist = file_playlists[idx]

                audio = track.get("hide", "") == "video"
                track_kind = "audio" if audio else "video"
                track_name = self._properties(this_playlist).get("shotcut:name", f"Track {idx}")

                blend = not audio and (str(track_idx) in blends)

                clips: dict[int, TimelineClip] = {}
                transitions: dict[int, TimelineTransition] = {}
                cursor = Decimal(0)
                for elem in this_playlist:
                    if elem.tag == "blank":
                        cursor += parse_time(elem.attrib["length"])

                    elif elem.tag == "entry":
                        producer_name = elem.attrib["producer"]

                        if producer_name.startswith("tractor"):
                            transition_element = root.find(
                                f"tractor[@id='{producer_name}']"
                            )
                            if transition_element is None:
                                continue

                            transition_object = Transition.from_xml(transition_element)
                            transitions[transition_object.index] = TimelineTransition(
                                start=cursor,
                                transition=transition_object,
                                track=idx,
                            )
                            cursor += transition_object.duration

                        elif producer_name.startswith("chain") or producer_name.startswith("producer"):
                            clip_element = self._find_element(root, producer_name)
                            if clip_element is None:
                                continue
                            clip_properties = self._properties(clip_element)
                            clip_properties.pop("shotcut:hash", None)

                            clip_index = int(search(r"\d+", producer_name).group())
                            clip_path = Path(clip_properties["resource"])
                            in_point = parse_time(elem.attrib["in"])
                            out_point = parse_time(elem.attrib["out"])
                            duration = out_point - in_point

                            for asset in self.assets.values():
                                if asset.path == clip_path:
                                    bin_asset = asset.index
                                    break
                            else:
                                clip_path_str = clip_properties.get("resource", "")
                                colon_idx = clip_path_str.find(":")
                                if colon_idx > 0 and all(
                                    c in "0123456789." for c in clip_path_str[:colon_idx]
                                ):
                                    actual_path = Path(clip_path_str[colon_idx + 1:])
                                    for asset in self.assets.values():
                                        if asset.path == actual_path:
                                            bin_asset = asset.index
                                            break
                                    else:
                                        bin_asset = clip_index
                                else:
                                    bin_asset = clip_index

                            clip_filters: list[Element] = []
                            for filt_elem in clip_element.findall("filter"):
                                clip_filters.append(filt_elem)

                            clips[clip_index] = TimelineClip(
                                index=clip_index,
                                bin_asset_id=bin_asset,
                                track=idx,
                                start=cursor,
                                duration=duration,
                                source_in=in_point,
                                source_out=out_point,
                                filters=clip_filters,
                            )
                            cursor += duration

                track_filters: list[tuple[str, str, dict[str, str]]] = []
                for filt_elem in this_playlist.findall("filter"):
                    filt_id = filt_elem.get("id", "")
                    filt_out = filt_elem.get("out", zero_time())
                    filt_props = self._properties(filt_elem)
                    track_filters.append((filt_id, filt_out, filt_props))

                tracks[idx] = Track(
                    index=idx,
                    name=track_name,
                    kind=track_kind,
                    clips=clips,
                    transitions=transitions,
                    blend=blend,
                    filters=track_filters,
                )

        self.timeline = Timeline(tracks=tracks, markers=markers)
        assert self.timeline.main_video
        assert self.timeline.main_audio

        # we also need to capture any unused transitions
        for transition in self._transitions.values():
            for clip_index, clip_in, clip_out in [
                (transition.left_clip, None, transition.transition.clip_start_out),
                (transition.right_clip, transition.transition.clip_end_in, None),
            ]:
                if clip_index in self._clips:
                    continue
                this_track = self.timeline.tracks[transition.track]
                existing = this_track.transition_only_clips

                clip_element = self._find_element(root, f"chain{clip_index}")
                if clip_element is None:
                    clip_element = self._find_element(root, f"producer{clip_index}")
                if clip_element is not None:
                    clip_properties = self._properties(clip_element)
                    clip_properties.pop("shotcut:hash", None)

                    clip_path = Path(clip_properties["resource"])
                    in_point = (
                        clip_in
                        if clip_in is not None
                        else clip_out - transition.duration
                    )
                    out_point = (
                        clip_out
                        if clip_out is not None
                        else clip_in + transition.duration
                    )
                    clip_duration = out_point - in_point

                    bin_asset = -1
                    for asset in self.assets.values():
                        if asset.path == clip_path:
                            bin_asset = asset.index
                            break
                    if bin_asset < 0:
                        clip_path_str = clip_properties.get("resource", "")
                        colon_idx = clip_path_str.find(":")
                        if colon_idx > 0 and all(
                            c in "0123456789." for c in clip_path_str[:colon_idx]
                        ):
                            actual_path = Path(clip_path_str[colon_idx + 1:])
                            for asset in self.assets.values():
                                if asset.path == actual_path:
                                    bin_asset = asset.index
                                    break
                    if bin_asset < 0:
                        bin_asset = clip_index

                    existing[clip_index] = TimelineClip(
                        index=clip_index,
                        bin_asset_id=bin_asset,
                        track=transition.track,
                        start=cursor,
                        duration=clip_duration,
                        source_in=in_point,
                        source_out=out_point,
                    )

                this_track.transition_only_clips = existing
                self.timeline.tracks[transition.track] = this_track

    @property
    def _tracks(self) -> dict[int, Track]:
        return self.timeline.tracks

    @property
    def _clips(self) -> dict[int, TimelineClip]:
        clips: dict[int, TimelineClip] = {}
        for track in self.timeline.tracks.values():
            for idx, clip in track.clips.items():
                if idx not in clips:
                    clips[idx] = clip

            for idx, clip in track.transition_only_clips.items():
                if idx not in clips:
                    clips[idx] = clip
        return clips

    @property
    def _transitions(self) -> dict[int, TimelineTransition]:
        transitions: dict[int, TimelineTransition] = {}
        for track in self.timeline.tracks.values():
            for idx, transition in track.transitions.items():
                assert (
                    idx not in transitions
                ), f"Colliding transitions: {idx} -> {transitions[idx]} & {transition}"
                transitions[idx] = transition
        return transitions

    @property
    def _markers(self) -> dict[int, Marker]:
        return self.timeline.markers

    def _max(self, mapping: dict[int, Any]) -> int:
        return max(mapping.keys(), default=-1)

    def _next(self, iter: list[int] | set[int], start_at: int = 0) -> int:
        if not iter:
            return start_at
        missing = set(range(start_at, max(iter) + 2)).difference(iter)
        return min(missing)

    def _next_mapping(self, mapping: dict[int, Any]) -> int:
        return self._next(list(mapping.keys()))

    def create_element(
        self,
        tag: str,
        attributes: dict[str, Any] = {},
        properties: dict[str, Any] = {},
        extras: list[Element] = [],
    ) -> Element:
        elem = Element(tag, {k: str(v) for k, v in attributes.items()})
        elem.extend(self._create_properties(properties))
        elem.extend(extras)
        return elem

    def _create_property(self, key: str, value: str | float | int) -> Element:
        prop = Element("property", {"name": key})
        prop.text = str(value)
        return prop

    def _create_properties(self, data: dict[str, Any]) -> list[Element]:
        return [self._create_property(k, v) for k, v in data.items()]

    def _write_assets(self, root: Element) -> None:
        main = self._find_tractor(root)

        for asset in self.assets.values():
            tag = "producer" if asset.is_producer else "chain"
            attrib = {k: v for k, v in asset.attrib.items() if k not in ("in", "out")}
            attrib["id"] = f"{tag}{asset.index}"
            attrib["out"] = asset.duration_string

            props = dict(asset.properties)
            props["length"] = asset.duration_string
            props["resource"] = str(asset.path)
            props["mlt_service"] = asset.mlt_service

            root.append(self.create_element(tag, attributes=attrib, properties=props))

        # ._write_chains will also write chains for assets that are timeline clips.
        # Those chains may have different durations (clip vs full asset).

        root.append(
            self.create_element(
                "playlist",
                attributes={
                    "id": self.details["producer"],
                    "title": self.details["title"],
                },
                properties={
                    "shotcut:projectAudioChannels": 2,
                    "shotcut:projectFolder": 1,
                    "shotcut:processingMode": "Native8Cpu",
                    "shotcut:skipConvert": 0,
                    "xml_retain": 1,
                },
                extras=[
                    Element(
                        "entry",
                        {
                            "producer": f"{'producer' if asset.is_producer else 'chain'}{asset.index}",
                            "in": zero_time(),
                            "out": asset.duration_string,
                        },
                    )
                    for asset in self.assets.values()
                ],
            )
        )

        root.append(
            self.create_element(
                "producer",
                attributes={
                    "id": "black",
                    "in": zero_time(),
                    "out": self.timeline.duration_string,
                },
                properties={
                    "length": self.timeline.duration_string,
                    "eof": "pause",
                    "resource": 0,
                    "aspect_ratio": 1,
                    "mlt_service": "color",
                    "mlt_image_format": "rgba",
                    "set.test_audio": 0,
                },
            )
        )

        root.append(
            self.create_element(
                "playlist",
                attributes={"id": "background"},
                extras=[
                    Element(
                        "entry",
                        {
                            "producer": "black",
                            "in": zero_time(),
                            "out": self.timeline.duration_string,
                        },
                    )
                ],
            )
        )

        main.append(self.create_element("track", {"producer": "background"}))

    def _write_chains(self, root: Element) -> None:
        sorted_clips = sorted(
            self._clips.values(),
            key=lambda c: (c.track, c.start),
        )
        for clip in sorted_clips:
            my_bin = self.assets[clip.bin_asset_id]

            attrib = {k: v for k, v in my_bin.attrib.items() if k not in ("in", "out")}
            attrib["id"] = f"chain{clip.index}"
            attrib["out"] = my_bin.duration_string

            props = dict(my_bin.properties)
            props["length"] = my_bin.duration_string
            props["resource"] = str(my_bin.path)
            props["mlt_service"] = my_bin.mlt_service

            chain_elem = self.create_element("chain", attributes=attrib, properties=props)

            for filt_elem in clip.filters:
                chain_elem.append(deepcopy(filt_elem))

            root.append(chain_elem)

        # Remove duplicate chain elements with same ID (clip chain may duplicate
        # an earlier asset chain when clip.index == asset.index).
        seen: set[str] = set()
        for elem in list(root.findall("chain")):
            cid = elem.get("id", "")
            if cid in seen:
                root.remove(elem)
            else:
                seen.add(cid)

    def _write_transitions(self, root: Element) -> None:
        clips = self._clips

        for track in self._tracks.values():
            valid_transitions: dict[int, TimelineTransition] = {}

            for transition in sorted(
                track.transitions.values(),
                key=lambda t: t.start,
            ):

                if transition.left_clip not in clips:
                    continue
                if transition.right_clip not in clips:
                    continue
                if transition.duration < Decimal(1) / Decimal(self.framerate):
                    continue

                valid_transitions[transition.index] = transition

                new_xml = transition.transition.to_xml()

                right_chain_id = f"chain{transition.right_clip}"
                for idx, elem in enumerate(list(root)):
                    if elem.tag == "chain" and elem.get("id") == right_chain_id:
                        root.insert(idx + 1, new_xml)
                        break
                else:
                    raise ValueError(
                        f"Could not find chain {right_chain_id} for transition {transition.index}"
                    )

            self.timeline.tracks[track.index].transitions = valid_transitions

    def _write_playlists(self, root: Element) -> None:
        main = self._find_tractor(root)

        for track in self._tracks.values():
            if not track.sorted_all:
                if track.index not in [
                    self.timeline.main_video.index,
                    self.timeline.main_audio.index,
                ]:
                    continue

            this_playlist = self.create_element(
                "playlist",
                attributes={"id": f"playlist{track.index}"},
                properties={
                    "shotcut:name": track.name,
                    f"shotcut:{track.kind}": 1,
                },
            )

            entries = track.sorted_all
            cursor = Decimal(0)

            for entry in entries:
                if entry.start > cursor:
                    gap = entry.start - cursor
                    this_playlist.append(Element("blank", {"length": format_time(gap)}))
                    cursor += gap

                if isinstance(entry, TimelineTransition):
                    this_playlist.append(
                        Element(
                            "entry",
                            {
                                "producer": f"tractor{entry.index}",
                                "in": "00:00:00.000",
                                "out": entry.duration_string,
                            },
                        )
                    )
                else:
                    this_playlist.append(
                        Element(
                            "entry",
                            {
                                "producer": f"chain{entry.index}",
                                "in": entry.source_in_string,
                                "out": entry.source_out_string,
                            },
                        )
                    )
                cursor += entry.duration

            for filt_id, length, props in track.filters:
                this_playlist.append(
                    self.create_element(
                        "filter",
                        attributes={"id": filt_id, "out": length},
                        properties=props,
                    )
                )

            root.append(this_playlist)
            main.append(
                self.create_element(
                    "track",
                    {"producer": f"playlist{track.index}"}
                    | ({"hide": "video"} if track.kind == "audio" else {}),
                )
            )

    def _transition_base(self, id: int, A: str, B: str) -> Element:
        transition = Element("transition", {"id": f"transition{id}"})
        transition.extend(self._create_properties({"a_track": A, "b_track": B}))
        return transition

    def _create_audio_transition(self, id: int, A: str, B: str) -> Element:
        audio_transition = self._transition_base(id, A, B)
        audio_transition.extend(
            self._create_properties(
                {"mlt_service": "mix", "always_active": "1", "sum": "1"}
            )
        )
        return audio_transition

    def _create_video_transition(self, id: int, A: str, B: str) -> Element:
        video_transition = self._transition_base(id, A, B)
        video_transition.extend(
            self._create_properties(
                {
                    "version": "0.1",
                    "mlt_service": "frei0r.cairoblend",
                    "threads": "0",
                    "disable": "0",
                    "1": "normal",
                }
            )
        )
        return video_transition

    def _create_video_blend_transition(self, id: int, A: str, B: str) -> Element:
        video_transition = self._transition_base(id, A, B)
        video_transition.extend(
            self._create_properties(
                {
                    "compositing": "0",
                    "distort": "0",
                    "rotate_center": "0",
                    "mlt_service": "qtblend",
                    "threads": "0",
                    "disable": "0",
                }
            )
        )
        return video_transition

    def _write_blend_transitions(self, root) -> None:
        main = self._find_tractor(root)

        tracks: dict[str, tuple[str, bool]] = {
            str(idx): (track.attrib["producer"], track.get("hide", "") == "video")
            for idx, track in enumerate(main.findall("track"))
        }
        matrix: dict[str, list[str]] = {}
        for transition in main.findall("transition"):
            props = self._properties(transition)
            A, B = props["a_track"], props["b_track"]
            matrix.setdefault(A, [])
            if B not in matrix[A]:
                matrix[A].append(B)

        def _needs_mix(track_name: str) -> bool:
            if t := self._get_track(track_name.removeprefix("playlist")):
                return t.mix
            return False

        for A, (_, A_audio) in tracks.items():
            for B, (B_name, B_audio) in tracks.items():
                if int(A) >= int(B):
                    continue

                if A in matrix and B in matrix[A]:
                    continue

                transition_id = self._next_mapping(
                    self._all_objects(root, ".//transition")
                )

                both_audio = A_audio and B_audio
                mix_track = _needs_mix(B_name)

                if mix_track:
                    this_transition = self._create_audio_transition(transition_id, A, B)
                elif both_audio:
                    this_transition = self._create_audio_transition(transition_id, A, B)
                elif A_audio or B_audio:
                    if A_audio ^ B_audio and int(A) != 0:
                        continue
                    this_transition = self._create_audio_transition(transition_id, A, B)
                else:
                    if (
                        b_track := self._get_track(B_name.removeprefix("playlist"))
                    ) and (b_track.blend):
                        this_transition = self._create_video_blend_transition(
                            transition_id, A, B
                        )
                    else:
                        this_transition = self._create_video_transition(
                            transition_id, A, B
                        )

                main.append(this_transition)

                if mix_track and not A_audio and not B_audio:
                    video_id = self._next_mapping(
                        self._all_objects(root, ".//transition")
                    )
                    main.append(
                        self._create_video_transition(video_id, A, B)
                    )

    def _write_markers(self, root: Element) -> None:
        main = self._find_tractor(root)
        existing = main.find("properties[@name='shotcut:markers']")
        if existing is not None:
            main.remove(existing)
        if self._markers:
            main.append(
                self.create_element(
                    "properties",
                    attributes={"name": "shotcut:markers"},
                    extras=[
                        self.create_element(
                            "properties",
                            attributes={"name": marker.index},
                            properties={
                                "text": marker.text,
                                "start": marker.time_string,
                                "end": marker.time_string,
                                "color": marker.colour,
                            },
                        )
                        for marker in self._markers.values()
                    ],
                )
            )

    def _prune_chains(self, root: Element) -> None:
        used_clips = set(self._clips.keys())
        all_chains = self._all_objects(root, "chain")
        for idx, elem in all_chains.items():
            if idx in self.assets:
                continue

            if idx not in used_clips:
                root.remove(elem)

    def _prune_producers(self, root: Element) -> None:
        all_producers = self._all_objects(root, "producer")
        for idx, elem in all_producers.items():
            if idx in self.assets:
                continue
            root.remove(elem)

    def _prune_transitions(self, root: Element) -> None:
        main = self._find_tractor(root)

        used_tractors = set(self._transitions.keys())
        all_tractors = self._all_objects(root, "tractor")
        for idx, elem in all_tractors.items():
            if elem.attrib["id"] == main.attrib["id"]:
                continue

            if "shotcut:transition" not in self._properties(elem):
                continue

            if idx not in used_tractors:
                root.remove(elem)

    def _prune_playlists(self, root: Element) -> None:
        skip = [
            self.timeline.main_audio.index,
            self.timeline.main_video.index,
        ]

        empty_tracks = set(i for i, t in self._tracks.items() if not t.sorted_all)
        for i in empty_tracks:
            if i not in skip:
                del self.timeline.tracks[i]
                playlist_elem = root.find(f"playlist[@id='playlist{i}']")
                if playlist_elem is not None:
                    root.remove(playlist_elem)

        used_tracks = set(self._tracks.keys())
        all_playlists = self._all_objects(root, "playlist")
        for idx, elem in all_playlists.items():
            if not elem.attrib["id"].startswith("playlist"):
                continue

            if idx in skip:
                continue

            if idx not in used_tracks:
                root.remove(elem)

    def _prune_blend_transitions(self, root: Element) -> None:
        main = self._find_tractor(root)

        used_tracks = set(1 + t for t in self._tracks.keys())
        all_tracks = main.findall("track")
        tracks = [
            t for t in all_tracks if t.get("producer", "").startswith("playlist")
        ]

        # Tractor indices = enumerate positions of playlist tracks in all_tracks
        tractor_indices = sorted(
            i for i, t in enumerate(all_tracks)
            if t.get("producer", "").startswith("playlist")
        )
        used_playlists = set(tractor_indices)
        remap: dict[int, int] = {}

        new_idx = 1
        for track, tractor_idx in zip(tracks, tractor_indices):
            track_id = 1 + int(track.attrib["producer"].removeprefix("playlist"))
            if track_id not in used_tracks:
                main.remove(track)
                used_playlists.discard(tractor_idx)
                continue

            # only create remappings for maintained tracks
            remap[tractor_idx] = new_idx
            new_idx += 1

        for transition in list(main.findall("transition")):
            a_track = transition.find("./property[@name='a_track']")
            b_track = transition.find("./property[@name='b_track']")
            assert (
                a_track is not None and b_track is not None
            ), f"Corrupted transition {transition}"
            assert (
                a_track.text is not None and b_track.text is not None
            ), f"Corrupted transition {transition}"

            a_track_idx = int(a_track.text)
            b_track_idx = int(b_track.text)
            assert (
                a_track_idx is not None and b_track_idx is not None
            ), f"Corrupted transition {transition}"

            if a_track_idx == 0:
                # We don't touch the background blending ever
                continue

            if a_track_idx not in used_playlists or b_track_idx not in used_playlists:
                main.remove(transition)
            else:
                a_track.text = str(remap[a_track_idx])
                b_track.text = str(remap[b_track_idx])

    def _prune_markers(self, root: Element) -> None:
        main = self._find_tractor(root)

        used_markers = self.timeline.markers
        marker_container = main.find("properties[@name='shotcut:markers']")
        if marker_container is None:
            return

        XML_MARKERS = {
            int(marker.attrib["name"]): marker
            for marker in marker_container.findall("properties")
        }

        for idx, elem in XML_MARKERS.items():
            if idx not in used_markers:
                marker_container.remove(elem)

        if not marker_container.findall("properties"):
            main.remove(marker_container)

    def _defragment_chains(self, root: Element) -> None:
        all_chains = root.findall("chain")
        all_producers = root.findall("producer")

        for playlist in root.findall("playlist"):
            if playlist.get("id") == self.details["producer"]:
                bin_playlist = playlist
                break
        else:
            raise Exception("Could not find main bin")

        remap: dict[int, int] = {}
        next_id = 0
        for bin_chain in bin_playlist.findall("entry"):
            bin_idx = int(search(r"\d+", bin_chain.attrib["producer"]).group())
            remap[bin_idx] = next_id
            next_id += 1

        for chain in all_chains:
            chain_idx = int(search(r"\d+", chain.attrib["id"]).group())
            if chain_idx not in remap:
                remap[chain_idx] = next_id
                next_id += 1

        for prod in all_producers:
            if not (pd := search(r"\d+", prod.attrib.get("id", ""))):
                continue
            prod_idx = int(pd.group())
            if prod_idx not in remap:
                remap[prod_idx] = next_id
                next_id += 1

        # update chains as they exist
        for chain in all_chains:
            old_id = int(search(r"\d+", chain.attrib["id"]).group())
            new_id = remap[old_id]
            base_tag = chain.attrib["id"].rstrip("0123456789")
            chain.set("id", f"{base_tag}{new_id}")

        # update producers as they exist
        for prod in all_producers:
            if not (pd := search(r"\d+", prod.attrib.get("id", ""))):
                continue
            old_id = int(pd.group())
            new_id = remap.get(old_id, old_id)
            base_tag = prod.attrib["id"].rstrip("0123456789")
            prod.set("id", f"{base_tag}{new_id}")

        # update playlist entries
        for playlist in root.findall("playlist"):
            for entry in playlist.findall("entry"):
                producer = entry.attrib["producer"]
                base_tag = producer.rstrip("0123456789")
                if base_tag not in ("chain", "producer"):
                    continue

                old_id = int(search(r"\d+", producer).group())
                if old_id not in remap:
                    continue
                new_id = remap[old_id]
                entry.set("producer", f"{base_tag}{new_id}")

        # update tractors
        for tractor in root.findall("tractor"):
            for producer in tractor.findall("track"):
                p = producer.attrib["producer"]
                base_tag = p.rstrip("0123456789")
                if base_tag not in ("chain", "producer"):
                    continue

                old_id = int(search(r"\d+", p).group())
                if old_id not in remap:
                    continue
                new_id = remap[old_id]
                producer.set("producer", f"{base_tag}{new_id}")

        # update clips
        tracks: dict[int, Track] = {}
        for track in self.timeline.tracks.values():
            clips: dict[int, TimelineClip] = {}
            for clip in track.clips.values():
                old_clip_id = clip.index
                old_bin_id = clip.bin_asset_id
                new_clip_id = remap[old_clip_id]
                new_bin_id = remap.get(old_bin_id, old_bin_id)

                clip.index = new_clip_id
                clip.bin_asset_id = new_bin_id

                clips[clip.index] = clip

            track.clips = clips
            tracks[track.index] = track

        self.timeline.tracks = tracks

        # update transition clip references and transition_only_clips
        for track in self.timeline.tracks.values():
            for trans in track.transitions.values():
                trans.left_clip = remap.get(trans.left_clip, trans.left_clip)
                trans.right_clip = remap.get(trans.right_clip, trans.right_clip)
            tocs: dict[int, TimelineClip] = {}
            for clip in track.transition_only_clips.values():
                new_idx = remap.get(clip.index, clip.index)
                new_bin = remap.get(clip.bin_asset_id, clip.bin_asset_id)
                clip.index = new_idx
                clip.bin_asset_id = new_bin
                tocs[clip.index] = clip
            track.transition_only_clips = tocs

        new_assets: dict[int, BinAsset] = {}
        for old_id, asset in self.assets.items():
            new_id = remap.get(old_id, old_id)
            asset.index = new_id
            new_assets[new_id] = asset
        self.assets = new_assets

    def _defragment_transitions(self, root: Element) -> None:
        all_tractors = [
            tractor
            for tractor in root.findall("tractor")
            if "shotcut:transition" in self._properties(tractor)
        ]
        tractor_remap: dict[int, int] = {}
        transition_remap: dict[int, int] = {}
        for tractor in all_tractors:
            old_tractor_id = int(tractor.attrib["id"].removeprefix("tractor"))
            next_tractor_id = self._next(list(tractor_remap.values()))
            tractor_remap[old_tractor_id] = next_tractor_id

            for transition in tractor.findall("transition"):
                old_transition_idx = int(
                    transition.attrib["id"].removeprefix("transition")
                )
                next_transition_id = self._next(list(transition_remap.values()))
                transition_remap[old_transition_idx] = next_transition_id

        for tractor in all_tractors:
            old_tractor_id = int(tractor.attrib["id"].removeprefix("tractor"))
            new_tractor_id = tractor_remap[old_tractor_id]
            tractor.set("id", f"tractor{new_tractor_id}")

            for transition in tractor.findall("transition"):
                old_transition_idx = int(
                    transition.attrib["id"].removeprefix("transition")
                )
                new_tractor_id = transition_remap[old_transition_idx]

                transition.set("id", f"transition{new_tractor_id}")

        # update playlist entry producer references for tractors
        for playlist in root.findall("playlist"):
            for entry in playlist.findall("entry"):
                producer = entry.attrib["producer"]
                if not producer.startswith("tractor"):
                    continue
                old_id = int(search(r"\d+", producer).group())
                if old_id not in tractor_remap:
                    continue
                new_id = tractor_remap[old_id]
                entry.set("producer", f"tractor{new_id}")

        tracks: dict[int, Track] = {}
        for track in self.timeline.tracks.values():
            transitions: dict[int, TimelineTransition] = {}
            for track_transition in track.transitions.values():
                old_tractor_id = track_transition.index
                new_tractor_id = tractor_remap[old_tractor_id]

                old_audio_id = track_transition.transition.audio_transition.index
                old_video_id = track_transition.transition.video_transition.index
                new_audio_id = transition_remap[old_audio_id]
                new_video_id = transition_remap[old_video_id]

                track_transition.index = new_tractor_id
                track_transition.transition.audio_transition.index = new_audio_id
                track_transition.transition.video_transition.index = new_video_id

                transitions[track_transition.index] = track_transition

            track.transitions = transitions
            tracks[track.index] = track

        self.timeline.tracks = tracks

    def _defragment_playlists(self, root: Element) -> None:
        main = self._find_tractor(root)

        all_playlists = root.findall("playlist")

        remap: dict[int, int] = {}
        next_id = 0
        for playlist in all_playlists:
            if not playlist.attrib["id"].startswith("playlist"):
                continue

            old_id = int(playlist.attrib["id"].removeprefix("playlist"))
            remap[old_id] = next_id
            next_id += 1

        # update playlists
        for playlist in all_playlists:
            if not playlist.attrib["id"].startswith("playlist"):
                continue

            old_id = int(playlist.attrib["id"].removeprefix("playlist"))
            new_playlist_id = remap[old_id]

            playlist.set("id", f"playlist{new_playlist_id}")

        # update the main tractor
        for xml_track in main.findall("track"):
            if not xml_track.attrib["producer"].startswith("playlist"):
                continue

            old_producer_id = int(xml_track.attrib["producer"].removeprefix("playlist"))
            new_producer_id = remap[old_producer_id]
            xml_track.set("producer", f"playlist{new_producer_id}")

        # update tracks
        tracks: dict[int, Track] = {}
        for track in self.timeline.tracks.values():
            old_track_id = track.index
            new_track_id = remap[old_track_id]
            track.index = new_track_id
            tracks[track.index] = track
        self.timeline.tracks = tracks

    def _defragment_markers(self, root: Element) -> None:
        main = self._find_tractor(root)

        marker_container = main.find("properties[@name='shotcut:markers']")
        if marker_container is None:
            return

        all_markers = marker_container.findall("properties")
        all_markers.sort(
            key=lambda m: (
                parse_time(start.text or "0")
                if (start := m.find("property[@name='start']")) is not None
                else Decimal(0)
            )
        )

        remap: dict[int, int] = {}
        next_id = 0
        for marker_elems in all_markers:
            old_id = int(marker_elems.attrib["name"])
            remap[old_id] = next_id
            next_id += 1

        for marker_elems in all_markers:
            old_id = int(marker_elems.attrib["name"])
            new_marker_id = remap[old_id]

            text_prop = marker_elems.find("property[@name='text']")
            if (
                text_prop is not None
                and text_prop.text
                and text_prop.text.startswith("Marker ")
            ):
                text_prop.text = f"Marker {new_marker_id+1}"

            marker_elems.set("name", str(new_marker_id))

        markers: dict[int, Marker] = {}
        for marker in self.timeline.markers.values():
            old_marker_id = marker.index
            new_marker_id = remap[old_marker_id]
            marker.index = new_marker_id
            marker.text = (
                f"Marker {marker.index+1}"
                if marker.text.startswith("Marker ")
                else marker.text
            )
            markers[marker.index] = marker
        self.timeline.markers = markers

    def _write_timeline(self, out: Path) -> None:
        # If the main bin uses a "playlistN" ID, timeline playlists would collide
        # when written with matching indices.  Rename to "main_bin" to keep IDs distinct.
        if self.details["producer"].startswith("playlist"):
            self.details["producer"] = "main_bin"

        root = Element("mlt", self.details)
        new_tree = ElementTree(root)
        root.append(Element("profile", self.profile))
        root.append(
            self.create_element(
                "tractor",
                {
                    "id": f"tractor{max(self._transitions.keys(), default=-1)+1}",
                    "title": self.details["title"],
                    "in": zero_time(),
                    "out": self.timeline.duration_string,
                },
                properties={
                    "shotcut": 1,
                    "shotcut:projectAudioChannels": 2,
                    "shotcut:projectFolder": 1,
                    "shotcut:processingMode": "Native8Cpu",
                    "shotcut:skipConvert": 0,
                },
            )
        )

        self._write_assets(root)
        self._write_chains(root)
        self._write_transitions(root)

        # Prune empty tracks before writing playlists so tractor tracks stay in sync
        self._prune_playlists(root)

        self._write_playlists(root)
        self._write_blend_transitions(root)
        self._write_markers(root)

        self._prune_chains(root)
        self._prune_producers(root)
        self._prune_transitions(root)
        self._prune_blend_transitions(root)
        self._prune_markers(root)

        self._defragment_chains(root)
        self._defragment_transitions(root)
        self._defragment_playlists(root)
        self._defragment_markers(root)

        main = root.find(f"tractor[@title='{self.details['title']}']")
        if main is not None:
            root.remove(main)
            root.append(main)

        indent(new_tree)
        new_tree.write(out, encoding="utf-8", xml_declaration=True)

    def save(self, path: Optional[Path] = None) -> None:
        self._write_timeline(path or self.path)

    def _get_track(self, track_name_id_or_obj: int | str | Track) -> Track | None:
        if isinstance(track_name_id_or_obj, Track):
            return track_name_id_or_obj
        elif isinstance(track_name_id_or_obj, int):
            return self._tracks[track_name_id_or_obj]
        elif isinstance(track_name_id_or_obj, str):
            for track_iter in self._tracks.values():
                if track_iter.name == track_name_id_or_obj:
                    return track_iter
        return None

    def get_track(self, track_name_id_or_obj: int | str | Track) -> Track:
        if track := self._get_track(track_name_id_or_obj=track_name_id_or_obj):
            return track

        raise ValueError(f"Could not find track '{track_name_id_or_obj}'")

    def create_track(self, name: str, kind: Literal["video", "audio"]) -> Track:
        idx = self._next_mapping(self._tracks)

        new_track = Track(index=idx, name=name, kind=kind, clips={}, transitions={})

        self.timeline.tracks[idx] = new_track
        return new_track

    def find_assets_by_path(self, path: Path) -> list[BinAsset]:
        return [a for a in self.assets.values() if a.path == path]

    def get_or_create_track(self, name: str, kind: Literal["video", "audio"]) -> Track:
        if track := self._get_track(track_name_id_or_obj=name):
            assert (
                track.kind == kind
            ), f"Found track '{name}' but it was '{track.kind}' not '{kind}'"
            return track

        return self.create_track(name, kind=kind)

    def add_clip_to_track(
        self,
        track: Track,
        bin_asset_id: int,
        start: Decimal,
        duration: Decimal,
        source_in: Decimal = Decimal(0),
    ) -> TimelineClip:
        idx = self._next_mapping(track.clips)
        clip = TimelineClip(
            index=idx,
            bin_asset_id=bin_asset_id,
            track=track.index,
            start=start,
            duration=duration,
            source_in=source_in,
            source_out=source_in + duration,
        )
        track.clips[idx] = clip
        self.timeline.tracks[track.index] = track
        return clip

    def clear_track(self, track: Track) -> None:
        track.clips.clear()
        track.transitions.clear()
        track.filters.clear()
        self.timeline.tracks[track.index] = track

    def add_filter_to_track(
        self,
        track: Track,
        filter_id: str,
        length: str,
        properties: dict[str, str],
    ) -> None:
        track.filters.append((filter_id, length, dict(properties)))
        self.timeline.tracks[track.index] = track

    def remove_filter_from_track(
        self,
        track: Track,
        filter_id: str,
    ) -> None:
        track.filters = [(fid, length, props) for fid, length, props in track.filters if fid != filter_id]
        self.timeline.tracks[track.index] = track

    def add_transition_to_track(
        self,
        track: Track,
        transition: Transition,
        start: Decimal,
    ) -> TimelineTransition:
        if start not in {t.start for t in track.transitions.values()}:
            pass
        timeline_transition = TimelineTransition(
            start=start,
            track=track.index,
            transition=transition,
        )
        track.transitions[transition.index] = timeline_transition
        self.timeline.tracks[track.index] = track
        return timeline_transition

    def find_markers(self) -> list[tuple[Decimal, Decimal]]:
        marker_times = sorted(
            (marker.time for marker in self.timeline.markers.values()),
        )
        if not marker_times:
            duration = self.timeline.duration
            return [(Decimal(0), duration)]

        if len(marker_times) % 2:
            marker_times.append(self.timeline.duration)

        return list(zip(marker_times[::2], marker_times[1::2]))

    def clear_markers(self) -> None:
        self.timeline.markers.clear()

    def add_marker(
        self, time: Decimal, text: str = "", colour: str = "#008000"
    ) -> None:
        idx = self._next_mapping(self._markers)
        self.timeline.markers[idx] = Marker(
            index=idx, text=text or f"Marker {idx+1}", time=time, colour=colour
        )

    def _heal_transitions(self) -> None:
        remove = set()
        for transition in self._transitions.values():
            if transition.left_clip not in self._clips:
                remove.add(transition.index)
            if transition.right_clip not in self._clips:
                remove.add(transition.index)

        for track in self.timeline.tracks.values():
            for rem in remove:
                if rem in track.transitions:
                    track.transitions.pop(rem)
            self.timeline.tracks[track.index] = track

    def _get_clip_transitions(self, clip: TimelineClip) -> list[TimelineTransition]:
        return [
            transition
            for transition in self._transitions.values()
            if transition.left_clip == clip.index or transition.right_clip == clip.index
        ]

    def _update_cut_clip_transitions(
        self,
        initial_clip: TimelineClip,
        left_clip: Optional[TimelineClip] = None,
        right_clip: Optional[TimelineClip] = None,
    ) -> None:
        for transition in self._get_clip_transitions(initial_clip):
            remove = False

            if left_clip is None:
                remove = True
            elif right_clip is None:
                remove = True

            elif transition.right_clip == initial_clip.index:
                transition.right_clip = left_clip.index

            elif transition.left_clip == initial_clip.index:
                transition.left_clip = right_clip.index

            track = self.timeline.tracks[transition.track]

            if remove:
                track.transitions.pop(transition.index)
            else:
                track.transitions[transition.index] = transition

    def _split_clip(
        self,
        clip: TimelineClip,
        raw_time: Optional[Decimal] = None,
        relative_time: Optional[Decimal] = None,
    ) -> tuple[TimelineClip, TimelineClip]:
        assert (raw_time is None) ^ (relative_time is None), "Provide exactly one time"

        clip_time = (raw_time - clip.start) if raw_time is not None else relative_time

        assert clip_time, "Must provide a raw time or relative time to clip from"
        assert Decimal(0) < clip_time < clip.duration, "Split time is outside clip"

        first = TimelineClip(
            index=clip.index,
            bin_asset_id=clip.bin_asset_id,
            track=clip.track,
            start=clip.start,
            duration=clip_time,
            source_in=clip.source_in,
            source_out=clip.source_in + clip_time,
        )

        second = TimelineClip(
            index=self._next_mapping(self._clips),
            bin_asset_id=clip.bin_asset_id,
            track=clip.track,
            start=clip.start + clip_time,
            duration=clip.duration - clip_time,
            source_in=clip.source_in + clip_time,
            source_out=clip.source_out,
        )

        return first, second

    def split_clip(self, clip: TimelineClip, offset: Decimal) -> None:
        track = self.timeline.tracks[clip.track]
        first, second = self._split_clip(clip, relative_time=offset)
        track.clips.pop(clip.index)
        track.clips[first.index] = first
        track.clips[second.index] = second
        self.timeline.tracks[track.index] = track

        self._update_cut_clip_transitions(
            initial_clip=clip, left_clip=first, right_clip=second
        )

    def cut_from_clip(
        self, clip: TimelineClip, offset: Decimal, duration: Decimal
    ) -> None:
        track = self.timeline.tracks[clip.track]
        first, residue = self._split_clip(clip, relative_time=offset)
        track.clips[first.index] = first

        second = None
        if duration < residue.duration:
            _, second = self._split_clip(residue, relative_time=duration)
            track.clips[second.index] = second

        self.timeline.tracks[track.index] = track

        self._update_cut_clip_transitions(
            initial_clip=clip, left_clip=first, right_clip=second
        )

    def split_track(self, track: Track, time: Decimal) -> None:
        for clip in track.sorted_clips:
            if clip.start < time < clip.end:
                first, second = self._split_clip(clip, raw_time=time)
                track.clips[clip.index] = first
                track.clips[second.index] = second

                self._update_cut_clip_transitions(
                    initial_clip=clip, left_clip=first, right_clip=second
                )
        self.timeline.tracks[track.index] = track

    def cut_from_track(self, track: Track, time: Decimal, duration: Decimal) -> None:
        start = time
        end = start + duration
        for obj in track.sorted_all:
            if obj.end < start or obj.start > end:
                continue

            # the object is completely in the cut
            if obj.start > start and obj.end < end:
                if isinstance(obj, TimelineClip):
                    track.clips.pop(obj.index)
                elif isinstance(obj, TimelineTransition):
                    track.transitions.pop(obj.index)
                continue

            # the cut is fully within the bounds of the object
            if obj.start < start and obj.end > end:
                if isinstance(obj, TimelineClip):
                    first, residue = self._split_clip(obj, raw_time=start)
                    _, second = self._split_clip(residue, raw_time=end)
                    track.clips.pop(obj.index)
                    track.clips[first.index] = first
                    track.clips[second.index] = second

                    self._update_cut_clip_transitions(
                        initial_clip=obj, left_clip=first, right_clip=second
                    )

                elif isinstance(obj, TimelineTransition):
                    # You cannot cut a transition
                    pass

            # the cut is only the end of the object
            elif start < obj.end < end:
                if isinstance(obj, TimelineClip):
                    kept_start, _ = self._split_clip(obj, raw_time=start)
                    track.clips.pop(obj.index)
                    track.clips[kept_start.index] = kept_start

                    self._update_cut_clip_transitions(
                        initial_clip=obj, left_clip=kept_start
                    )

                elif isinstance(obj, TimelineTransition):
                    # You cannot cut a transition
                    pass

            # the cut is only the start of the object
            else:
                if isinstance(obj, TimelineClip):
                    _, kept_end = self._split_clip(obj, raw_time=end)
                    track.clips.pop(obj.index)
                    track.clips[kept_end.index] = kept_end

                    self._update_cut_clip_transitions(
                        initial_clip=obj, right_clip=kept_end
                    )

                elif isinstance(obj, TimelineTransition):
                    # You cannot cut a transition
                    pass

        self.timeline.tracks[track.index] = track
        self._heal_transitions()

    def _collect_block(
        self,
        timeline_object: TimelineClip | TimelineTransition,
        left_transitions_strategy: TransitionStrategy = TransitionStrategy.GROW_OR_KEEP,
        right_transitions_strategy: TransitionStrategy = TransitionStrategy.GROW_OR_MOVE,
    ) -> list[TimelineClip | TimelineTransition]:
        track = self.timeline.tracks[timeline_object.track]
        everything = track.sorted_all
        my_pos = everything.index(timeline_object)
        before, me, after = (
            everything[:my_pos][::-1],
            everything[my_pos],
            everything[my_pos + 1 :],
        )

        pre_block: list[TimelineClip | TimelineTransition] = []
        post_block: list[TimelineClip | TimelineTransition] = []

        if after:
            if right_transitions_strategy in [
                TransitionStrategy.KEEP,
                TransitionStrategy.GROW_OR_KEEP,
            ]:
                pass
            elif right_transitions_strategy in [
                TransitionStrategy.MOVE,
                TransitionStrategy.GROW_OR_MOVE,
            ]:
                if isinstance(after[0], TimelineTransition):
                    if after[0].left_clip == me.index:
                        post_block.append(after[0])
            elif right_transitions_strategy in [TransitionStrategy.GLUE]:
                for after_objs in after:
                    prev_obj = post_block[-1] if len(post_block) > 0 else me
                    if isinstance(after_objs, TimelineClip) and isinstance(
                        prev_obj, TimelineTransition
                    ):
                        if prev_obj.right_clip == after_objs.index:
                            post_block.append(after_objs)
                            continue
                    elif isinstance(after_objs, TimelineTransition) and isinstance(
                        prev_obj, TimelineClip
                    ):
                        if after_objs.left_clip == prev_obj.index:
                            post_block.append(after_objs)
                            continue
                    break

        if before:
            if left_transitions_strategy in [
                TransitionStrategy.KEEP,
                TransitionStrategy.GROW_OR_KEEP,
            ]:
                pass
            elif left_transitions_strategy in [
                TransitionStrategy.MOVE,
                TransitionStrategy.GROW_OR_MOVE,
            ]:
                if isinstance(before[0], TimelineTransition):
                    if before[0].right_clip == me.index:
                        pre_block.append(before[0])
            elif left_transitions_strategy in [TransitionStrategy.GLUE]:
                for before_objs in before:
                    next_obj = pre_block[-1] if len(pre_block) > 0 else me
                    if isinstance(before_objs, TimelineClip) and isinstance(
                        next_obj, TimelineTransition
                    ):
                        if next_obj.left_clip == before_objs.index:
                            pre_block.append(before_objs)
                            continue
                    elif isinstance(before_objs, TimelineTransition) and isinstance(
                        next_obj, TimelineClip
                    ):
                        if before_objs.right_clip == next_obj.index:
                            pre_block.append(before_objs)
                            continue
                    break

        return pre_block[::-1] + [me] + post_block

    def _mov_obj(
        self,
        timeline_object: TimelineClip | TimelineTransition,
        new_track: Optional[Track] = None,
        new_time: Optional[Decimal] = None,
        strategy: CollisionStrategy = CollisionStrategy.REJECT,
        left_transitions_strategy: TransitionStrategy = TransitionStrategy.GROW_OR_KEEP,
        right_transitions_strategy: TransitionStrategy = TransitionStrategy.GROW_OR_MOVE,
    ) -> None:
        assert not (
            new_time is None and new_track is None
        ), "Provide at least one option"

        block_to_move = self._collect_block(
            timeline_object,
            left_transitions_strategy=left_transitions_strategy,
            right_transitions_strategy=right_transitions_strategy,
        )
        start = min(o.start for o in block_to_move)
        block_duration = max(o.end for o in block_to_move) - start
        new_start = new_time or start
        new_end = new_start + block_duration

        moved_from_track = self.timeline.tracks[timeline_object.track]
        # pre-cleanup the old track
        for obj in block_to_move:
            moved_from_track.remove(obj)

        # make sure we shunt to their new times as well
        diff = new_start - start
        moved_block: list[TimelineClip | TimelineTransition] = []
        for obj in block_to_move:
            obj.start += diff
            moved_block.append(obj)

        moved_to_track = (
            self.timeline.tracks[new_track.index]
            if new_track is not None
            else moved_from_track
        )

        # collect everything that is colliding
        colliding_objects: list[TimelineClip | TimelineTransition] = []
        for obj in moved_to_track.sorted_all:
            if obj.end > new_start and obj.start < new_end:
                colliding_objects.append(obj)

        # handle the collisions
        if colliding_objects:
            if strategy == CollisionStrategy.REJECT:
                raise ValueError(f"Collision with {colliding_objects}")

            if strategy == CollisionStrategy.SPLIT:

                # we can only split the first/last clips that overlap the block, everything else is lost
                split_start = colliding_objects.pop(0)
                moved_to_track.remove(split_start)
                if isinstance(split_start, TimelineClip):
                    keep, _ = self._split_clip(split_start, raw_time=new_start)
                    moved_to_track.clips[keep.index] = keep
                    self._update_cut_clip_transitions(
                        initial_clip=split_start, left_clip=keep
                    )

                if colliding_objects:
                    split_end = colliding_objects.pop(-1)
                    moved_to_track.remove(split_end)
                    if isinstance(split_end, TimelineClip):
                        _, keep = self._split_clip(split_end, raw_time=new_end)
                        moved_to_track.clips[keep.index] = keep
                        self._update_cut_clip_transitions(
                            initial_clip=split_end, right_clip=keep
                        )

            # remove the remaining clips after a split, or all of them for replace
            if strategy in [CollisionStrategy.REPLACE, CollisionStrategy.SPLIT]:
                for obj in colliding_objects:
                    moved_to_track.remove(obj)

            if strategy == CollisionStrategy.MOVE:
                # keep moving the colliding objects back in time, adding new colliding objects if neccesary
                seen = deepcopy(colliding_objects)
                while colliding_objects:
                    to_move = colliding_objects.pop(0)
                    moved_to_track.remove(to_move)
                    to_move.start = new_end
                    new_end = to_move.end
                    moved_block.append(to_move)

                    for obj in moved_to_track.sorted_all:
                        if (
                            obj.end > new_start
                            and obj.start < new_end
                            and obj not in seen
                        ):
                            colliding_objects.append(obj)
                            seen.append(obj)

        if left_clips := [o for o in moved_to_track.sorted_all if o.end < new_start]:
            left = left_clips[-1]
            if left_transitions_strategy in [
                TransitionStrategy.GROW_OR_KEEP,
                TransitionStrategy.GROW_OR_MOVE,
            ]:
                block_start = moved_block[0]
                if isinstance(block_start, TimelineClip) and isinstance(
                    left, TimelineTransition
                ):
                    if left.right_clip == block_start.index:
                        left.duration = block_start.start - left.start
                        moved_to_track.transitions[left.index] = left

                if isinstance(block_start, TimelineTransition) and isinstance(
                    left, TimelineClip
                ):
                    if block_start.left_clip == left.index:
                        block_start.duration = block_start.end - left.end
                        block_start.start = left.end
                        moved_block.pop(0)
                        moved_block.insert(0, block_start)

        if right_clips := [o for o in moved_to_track.sorted_all if o.start > new_end]:
            right = right_clips[0]
            if right_transitions_strategy in [
                TransitionStrategy.GROW_OR_KEEP,
                TransitionStrategy.GROW_OR_MOVE,
            ]:
                block_end = moved_block[-1]
                if isinstance(block_end, TimelineClip) and isinstance(
                    right, TimelineTransition
                ):
                    if right.left_clip == block_end.index:
                        right.duration = right.end - block_end.end
                        right.end = block_end.start
                        moved_to_track.transitions[right.index] = right

                if isinstance(block_end, TimelineTransition) and isinstance(
                    right, TimelineClip
                ):
                    if block_end.right_clip == right.index:
                        block_end.duration = right.start - block_end.start
                        moved_block.pop(-1)
                        moved_block.append(block_end)

        # write back the new clips/transitions for each track managed
        for obj in sorted(moved_block, key=lambda o: o.start):
            if isinstance(obj, TimelineClip):
                moved_to_track.clips[obj.index] = obj
            elif isinstance(obj, TimelineTransition):
                moved_to_track.transitions[obj.index] = obj

        self.timeline.tracks[moved_from_track.index] = moved_from_track
        self.timeline.tracks[moved_to_track.index] = moved_to_track
        self._heal_transitions()

    def move_clip(
        self,
        clip: TimelineClip,
        new_track: Optional[Track] = None,
        new_time: Optional[Decimal] = None,
        strategy: CollisionStrategy = CollisionStrategy.REJECT,
        left_transitions_strategy: TransitionStrategy = TransitionStrategy.GROW_OR_KEEP,
        right_transitions_strategy: TransitionStrategy = TransitionStrategy.GROW_OR_MOVE,
    ) -> None:
        self._mov_obj(
            clip,
            new_track=new_track,
            new_time=new_time,
            strategy=strategy,
            left_transitions_strategy=left_transitions_strategy,
            right_transitions_strategy=right_transitions_strategy,
        )

    def insert_time(
        self,
        track: Track,
        duration: Decimal,
        start_time: Decimal = Decimal(0),
        strategy=CollisionStrategy.SPLIT,
    ) -> None:
        new_track = self.timeline.tracks[track.index]
        for obj in track.sorted_all[::-1]:
            if isinstance(obj, TimelineClip):
                if obj.start > start_time:
                    obj.start += duration
                    new_track.clips[obj.index] = obj

                elif obj.end > start_time:
                    if strategy == CollisionStrategy.REJECT:
                        raise ValueError(f"New time intersects with {obj}")

                    new_track.remove(obj)
                    if strategy == CollisionStrategy.SPLIT:
                        keep, move = self._split_clip(obj, raw_time=start_time)
                        move.start += duration
                        new_track.clips[keep.index] = keep
                        new_track.clips[move.index] = move
                        self._update_cut_clip_transitions(
                            initial_clip=obj, left_clip=keep, right_clip=move
                        )

                    elif strategy == CollisionStrategy.MOVE:
                        obj.start += duration
                        new_track.clips[obj.index] = obj

            elif isinstance(obj, TimelineTransition):
                obj.start += duration
                new_track.transitions[obj.index] = obj

        self.timeline.tracks[track.index] = new_track
        self._heal_transitions()

    def remove_time(
        self,
        track: Track,
        duration: Decimal,
        start_time: Decimal = Decimal(0),
        strategy=CollisionStrategy.SPLIT,
    ) -> None:
        original_starts = {
            obj.index: obj.start
            for obj in track.sorted_all
            if isinstance(obj, TimelineTransition)
        }

        for obj in track.sorted_all:
            if obj.start > start_time and isinstance(obj, TimelineClip):
                self._mov_obj(obj, new_time=obj.start - duration, strategy=strategy)

        updated_track = self.timeline.tracks[track.index]
        for idx, orig_start in original_starts.items():
            if idx in updated_track.transitions and orig_start > start_time:
                transition = updated_track.transitions[idx]
                if transition.start == orig_start:
                    transition.start -= duration
                    updated_track.transitions[transition.index] = transition

        self.timeline.tracks[track.index] = updated_track

    def remove_transition(self, transition: TimelineTransition) -> None:
        track = self.timeline.tracks[transition.track]
        track.transitions.pop(transition.index)
        self.timeline.tracks[transition.track] = track

    def remove_clip(self, clip: TimelineClip) -> None:
        track = self.timeline.tracks[clip.track]
        track.clips.pop(clip.index)
        self.timeline.tracks[clip.track] = track

        for transition in self._get_clip_transitions(clip):
            self.remove_transition(transition)
        self._heal_transitions()

    def condense_clips(
        self,
        track: Track,
        after_time: Optional[Decimal] = None,
        up_to_time: Optional[Decimal] = None,
    ) -> None:
        start = after_time or Decimal(0)
        end = up_to_time or track.duration

        expected_pos = start
        for obj in track.sorted_all:
            if obj.start < start:
                continue

            if obj.end > end:
                break

            diff = obj.start - expected_pos
            obj.start -= diff
            expected_pos += obj.duration

            if isinstance(obj, TimelineClip):
                track.clips[obj.index] = obj
            elif isinstance(obj, TimelineTransition):
                track.transitions[obj.index] = obj

        self.timeline.tracks[track.index] = track
        self._heal_transitions()
