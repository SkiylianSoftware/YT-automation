from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from decimal import Decimal
from json import loads
from pathlib import Path
from re import compile
from subprocess import DEVNULL, PIPE, Popen, run
from tempfile import NamedTemporaryFile
from typing import Iterable, Optional

from alive_progress import alive_bar

from .shotcut import Shotcut, format_time

SILENCE_START = compile(r"silence_start:\s*(\d+(\.\d+)?)")
SILENCE_END = compile(r"silence_end:\s*(\d+(\.\d+)?)")


@dataclass(frozen=True)
class SilenceBlock:
    start: Decimal
    end: Decimal

    @property
    def duration(self) -> Decimal:
        return self.end - self.start

    def __str__(self):
        return f"{format_time(self.start)} to {format_time(self.end)}"


@dataclass(frozen=True)
class WordBlock(SilenceBlock):
    text: str

    def __str__(self):
        return f'"{self.text}" ({super().__str__()})'


@dataclass(frozen=True)
class SpeechBlock(SilenceBlock):
    text: str
    words: list[WordBlock]

    def __str__(self):
        return (
            f'"{self.text}" ({super().__str__()}) ['
            + "; ".join((str(w) for w in self.words))
            + "]"
        )


def file_duration(media: Path) -> Decimal:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(media.expanduser()),
    ]
    proc = run(cmd, stdout=PIPE, stderr=PIPE, text=True, check=True)
    return Decimal(loads(proc.stdout)["format"]["duration"])


def detect_silence(
    media: Path,
    channels: Optional[Iterable[int]] = None,
    threshold_db: int = -40,
    min_duration: Decimal = Decimal("0.15"),
) -> list[SilenceBlock]:
    silence_expr = f"silencedetect=n={threshold_db}dB:d={min_duration}"

    if channels is None:
        filter_cmd = ["-af", silence_expr]
    else:
        channels = list(channels)
        if len(channels) == 1:
            filter_cmd = [
                "-map",
                f"0:{channels[0]}",
                "-af",
                silence_expr,
            ]
        else:
            chans = "".join(f"[0:{ch}]" for ch in channels)
            filter_cmd = [
                "-filter_complex",
                f"{chans}amix=inputs={len(channels)},{silence_expr}",
            ]

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-i",
        str(media.expanduser()),
        *filter_cmd,
        "-f",
        "null",
        "-",
    ]

    proc = Popen(
        cmd,
        stderr=PIPE,
        stdout=DEVNULL,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    silences = []
    total = int(file_duration(media))

    end_time = None
    start_time = None
    with alive_bar(total, title=f"Parsing {media.name} for silence", unit="s") as bar:
        if proc.stderr:
            for line in proc.stderr:
                line = line.strip()

                if start := SILENCE_START.search(line):
                    start_time = Decimal(start.group(1))

                elif end := SILENCE_END.search(line):
                    end_time = Decimal(end.group(1))
                    assert (
                        start_time is not None
                    ), f"Found silence end ({end_time}) after silence start"
                    silences.append(
                        SilenceBlock(
                            start_time,
                            end_time,
                        )
                    )

                if now := end_time or start_time:
                    bar(int(now) - bar.current)

        bar(total - bar.current)

    proc.wait()

    return silences


def detect_words(
    media: Path,
    channels: Optional[Iterable[int]] = None,
    model_name="tiny.en",
    device: str = "cpu",
    compute_type: str = "int8",
) -> list[SpeechBlock]:
    tmp_file = None
    try:
        if channels is not None:
            tmp_file = NamedTemporaryFile(suffix=".wav")
            channels = list(channels)

            if len(channels) == 1:
                channel_filter = ["-map", f"0:{channels[0]}"]
            else:
                chans = "".join([f"[0:{ch}]" for ch in channels])
                channel_filter = [
                    "-filter_complex",
                    f"{chans}amix=inputs={len(channels)}[out]",
                    "-map",
                    "[out]",
                ]

            cmd = [
                "ffmpeg",
                "-err_detect",
                "ignore_err",
                "-y",
                "-i",
                str(media.expanduser()),
                *channel_filter,
                "-c:a",
                "pcm_s16le",
                str(tmp_file.name),
            ]
            run(cmd, stderr=DEVNULL, stdout=DEVNULL, check=True)

            audio_path = Path(tmp_file.name)
        else:
            audio_path = media.expanduser()

        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device=device, compute_type=compute_type)

        segments, _ = model.transcribe(
            str(audio_path),
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
        )

        result: list[SpeechBlock] = []
        with alive_bar(title=f"Parsing {media.name} for speech") as bar:
            for segment in segments:
                result.append(
                    SpeechBlock(
                        start=Decimal(str(segment.start)),
                        end=Decimal(str(segment.end)),
                        text=segment.text.strip(),
                        words=[
                            WordBlock(
                                start=Decimal(str(word.start)),
                                end=Decimal(str(word.end)),
                                text=word.word.strip(),
                            )
                            for word in (segment.words or [])
                        ],
                    )
                )
                bar()

        return result

    finally:
        if tmp_file is not None:
            tmp_file.close()
            tmp_file.delete = True


FILLER_WORDS = frozenset({
    "um", "umm", "uhh", "uh", "ahh", "ah", "erm", "er",
    "hmm", "mm", "mhm",
})


def detect_fillers(
    words: list[WordBlock],
    filler_set: set[str] = FILLER_WORDS,
) -> list[SilenceBlock]:
    found: list[SilenceBlock] = []
    for w in words:
        clean = w.text.lower().strip(".,!?;:\"'()[]{}")
        if clean in filler_set:
            found.append(SilenceBlock(start=w.start, end=w.end))
    return found


def detect_self_repairs(
    words: list[WordBlock],
    filler_set: set[str] = FILLER_WORDS,
) -> list[SilenceBlock]:
    found: list[SilenceBlock] = []
    for i in range(len(words) - 2):
        w0 = words[i].text.lower().strip(".,!?;:\"'()[]{}")
        w1 = words[i + 1].text.lower().strip(".,!?;:\"'()[]{}")
        w2 = words[i + 2].text.lower().strip(".,!?;:\"'()[]{}")
        if w0 == w2 and w1 in filler_set:
            start = words[i].start
            end = words[i + 1].end
            found.append(SilenceBlock(start=start, end=end))
    return found


def merge_regions(
    regions: list[SilenceBlock],
    padding: Decimal = Decimal("0.1"),
) -> list[SilenceBlock]:
    if not regions:
        return []

    sorted_regions = sorted(regions, key=lambda r: r.start)
    merged: list[SilenceBlock] = []
    current = SilenceBlock(
        start=sorted_regions[0].start - padding,
        end=sorted_regions[0].end + padding,
    )

    for region in sorted_regions[1:]:
        candidate = SilenceBlock(
            start=region.start - padding,
            end=region.end + padding,
        )
        if candidate.start <= current.end:
            current = SilenceBlock(
                start=min(current.start, candidate.start),
                end=max(current.end, candidate.end),
            )
        else:
            merged.append(current)
            current = candidate

    merged.append(current)
    return merged


def _media_silence_regions(
    shotcut: Shotcut,
    track_indices: list[int],
    channels: Optional[list[int]],
    threshold_db: int,
    min_silence: Decimal,
    max_silence: Optional[Decimal],
) -> dict[Path, list[SilenceBlock]]:
    media_map: dict[Path, list[int]] = {}
    for idx in track_indices:
        track = shotcut.timeline.tracks[idx]
        for clip in track.clips.values():
            asset = shotcut.assets[clip.bin_asset_id]
            path = asset.path
            if path not in media_map:
                media_map[path] = []
            media_map[path].append(clip.index)

    result: dict[Path, list[SilenceBlock]] = {}
    for media_path in media_map:
        silences = detect_silence(
            media=media_path,
            channels=channels,
            threshold_db=threshold_db,
            min_duration=min_silence,
        )
        if max_silence is not None:
            silences = [s for s in silences if s.duration <= max_silence]
        result[media_path] = silences

    return result


def _timeline_cut_regions(
    shotcut: Shotcut,
    track_indices: list[int],
    media_silences: dict[Path, list[SilenceBlock]],
    media_fillers: dict[Path, list[SilenceBlock]],
    media_repairs: dict[Path, list[SilenceBlock]],
    padding: Decimal = Decimal("0.1"),
) -> dict[int, list[SilenceBlock]]:
    cut_regions: dict[int, list[SilenceBlock]] = {idx: [] for idx in track_indices}

    for idx in track_indices:
        track = shotcut.timeline.tracks[idx]
        for clip in track.clips.values():
            asset = shotcut.assets[clip.bin_asset_id]
            media_path = asset.path
            media_start = clip.source_in
            media_end = clip.source_out

            all_regions = (
                media_silences.get(media_path, [])
                + media_fillers.get(media_path, [])
                + media_repairs.get(media_path, [])
            )

            for region in all_regions:
                cut_start = max(region.start - padding, media_start)
                cut_end = min(region.end + padding, media_end)
                if cut_start >= cut_end:
                    continue
                timeline_start = clip.start + (cut_start - media_start)
                timeline_end = clip.start + (cut_end - media_start)
                cut_regions[idx].append(
                    SilenceBlock(start=timeline_start, end=timeline_end)
                )

        cut_regions[idx] = merge_regions(cut_regions[idx], padding=Decimal(0))

    return cut_regions


def _apply_cuts(
    shotcut: Shotcut,
    cut_regions: dict[int, list[SilenceBlock]],
) -> None:
    all_regions: list[SilenceBlock] = []
    for regions in cut_regions.values():
        all_regions.extend(regions)
    all_regions = merge_regions(all_regions, padding=Decimal(0))

    if not all_regions:
        return

    for idx in cut_regions:
        track = shotcut.timeline.tracks[idx]
        for region in sorted(all_regions, key=lambda r: r.start, reverse=True):
            shotcut.cut_from_track(
                track, time=region.start, duration=region.duration
            )

            shotcut.remove_time(
                track, duration=region.duration, start_time=region.start
            )


def silence_removal(args: Namespace) -> int:
    project_path = Path(args.project).expanduser()
    sc = Shotcut(project_path)

    track_indices: list[int] = []
    for spec in args.tracks:
        if spec.isdigit():
            track_indices.append(int(spec))
        else:
            found = sc.timeline.track_by_name(spec)
            if found is not None:
                track_indices.append(found.index)

    channels: Optional[list[int]] = None
    if args.streams:
        channels = [int(s) for s in args.streams]

    threshold_db = getattr(args, "silence_threshold", -40)
    min_silence = Decimal(str(getattr(args, "silence_min_duration", "0.15")))

    max_silence: Optional[Decimal] = None
    if args.max_silence:
        max_silence = Decimal(str(args.max_silence))

    filler_set = set(FILLER_WORDS)
    if args.filler_words:
        filler_set.update(w.strip().lower() for w in args.filler_words.split(","))

    padding = Decimal(str(getattr(args, "padding", "0.1")))
    model = getattr(args, "model", "tiny.en")

    media_silences = _media_silence_regions(
        sc, track_indices, channels, threshold_db, min_silence, max_silence
    )

    media_fillers: dict[Path, list[SilenceBlock]] = {}
    media_repairs: dict[Path, list[SilenceBlock]] = {}
    for media_path in media_silences:
        words = detect_words(media=media_path, channels=channels, model_name=model)
        all_word_blocks = [w for seg in words for w in seg.words]
        media_fillers[media_path] = detect_fillers(all_word_blocks, filler_set)
        media_repairs[media_path] = detect_self_repairs(all_word_blocks, filler_set)

    cut_regions = _timeline_cut_regions(
        sc, track_indices, media_silences, media_fillers, media_repairs, padding
    )

    _apply_cuts(sc, cut_regions)

    output_path = args.output or project_path
    sc.save(Path(output_path).expanduser())
    return 0
