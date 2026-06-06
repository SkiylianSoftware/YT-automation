from __future__ import annotations

import wave
from argparse import Namespace
from dataclasses import dataclass, field
from decimal import Decimal
from json import loads
from pathlib import Path
from re import compile
from subprocess import DEVNULL, PIPE, Popen, run
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Iterable, Optional

import numpy as np
from alive_progress import alive_bar

from .shotcut import Shotcut, format_time

SILENCE_START = compile(r"silence_start:\s*(\d+(\.\d+)?)")
SILENCE_END = compile(r"silence_end:\s*(\d+(\.\d+)?)")
CHUNK_DURATION_S = 60


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
    prob: float = 0.0

    def __str__(self):
        return f'"{self.text}" ({super().__str__()})'


@dataclass(frozen=True)
class SentenceBlock(SilenceBlock):
    text: str

    def __str__(self):
        return f'"{self.text}" ({super().__str__()})'


@dataclass(frozen=True)
class SpeechBlock(SilenceBlock):
    text: str
    words: list[WordBlock] = field(default_factory=list)

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


def _merge_short_segments(
    blocks: list[SentenceBlock],
    max_gap_ms: int = 800,
    max_duration_ms: int = 8000,
) -> list[SentenceBlock]:
    if not blocks:
        return []
    merged: list[SentenceBlock] = [blocks[0]]
    for b in blocks[1:]:
        last = merged[-1]
        gap = float(b.start - last.end) * 1000
        cand_dur = float(b.end - last.start) * 1000
        if gap <= max_gap_ms and cand_dur <= max_duration_ms:
            merged[-1] = SentenceBlock(
                start=last.start,
                end=b.end,
                text=last.text + " " + b.text,
            )
        else:
            merged.append(b)
    return merged


def _split_long_segments(
    blocks: list[SentenceBlock],
    max_duration_s: Decimal = Decimal("8.0"),
) -> list[SentenceBlock]:
    import re as _re
    result: list[SentenceBlock] = []
    for b in blocks:
        duration = float(b.end - b.start)
        if duration <= float(max_duration_s):
            result.append(b)
            continue
        parts = _re.split(r"(?<=[.!?])\s+", b.text)
        if len(parts) < 2:
            result.append(b)
            continue
        total_chars = sum(len(p) for p in parts)
        cursor = float(b.start)
        for part in parts:
            frac = len(part) / total_chars
            part_end = cursor + duration * frac
            result.append(SentenceBlock(
                start=Decimal(str(cursor)),
                end=Decimal(str(part_end)),
                text=part,
            ))
            cursor = part_end
    return result


def _transcribe_chunks(
    audio: np.ndarray,
    model,
    sr: int = 16000,
    extract_words: bool = False,
    bar=None,
    language: str | None = None,
) -> list[SpeechBlock] | list[SentenceBlock]:
    import _pywhispercpp as pw

    ctx = model._ctx
    params = pw.whisper_full_default_params(
        pw.whisper_sampling_strategy.WHISPER_SAMPLING_GREEDY,
    )
    params.print_progress = False
    params.print_realtime = False
    params.n_threads = 4
    params.no_speech_thold = 0.2
    params.temperature = 0.0
    params.temperature_inc = 0.0
    params.token_timestamps = extract_words
    params.no_timestamps = False
    if language:
        params.language = language.encode()

    chunk_len = CHUNK_DURATION_S * sr
    n_chunks = (len(audio) + chunk_len - 1) // chunk_len

    blocks: list[SpeechBlock | SentenceBlock] = []

    for ci in range(n_chunks):
        start = ci * chunk_len
        end = min(start + chunk_len, len(audio))
        chunk = audio[start:end]
        if len(chunk) < sr:
            continue

        pw.whisper_full(ctx, params, chunk, len(chunk))
        n_seg = pw.whisper_full_n_segments(ctx)
        offset_ms = int(start / sr * 1000)

        for i in range(n_seg):
            t0 = pw.whisper_full_get_segment_t0(ctx, i) * 10 + offset_ms
            t1 = pw.whisper_full_get_segment_t1(ctx, i) * 10 + offset_ms
            text = pw.whisper_full_get_segment_text(ctx, i)

            if extract_words:
                n_tokens = pw.whisper_full_n_tokens(ctx, i)
                words: list[WordBlock] = []
                for j in range(n_tokens):
                    token_text = pw.whisper_full_get_token_text(ctx, i, j)
                    token_str = token_text.decode("utf-8", errors="replace").strip() if isinstance(token_text, bytes) else token_text.strip()
                    if token_str.startswith("[") and token_str.endswith("]"):
                        continue
                    p_data = pw.whisper_full_get_token_data(ctx, i, j)
                    prob = pw.whisper_full_get_token_p(ctx, i, j)

                    if not any(c.isalnum() for c in token_str):
                        if words:
                            prev = words[-1]
                            words[-1] = WordBlock(
                                start=prev.start,
                                end=Decimal(str((p_data.t1 * 10 + offset_ms) / 1000)),
                                text=prev.text + token_str,
                                prob=prev.prob,
                            )
                        continue

                    t_start = (p_data.t0 * 10 + offset_ms) / 1000
                    t_end = (p_data.t1 * 10 + offset_ms) / 1000
                    words.append(
                        WordBlock(
                            start=Decimal(str(t_start)),
                            end=Decimal(str(t_end)),
                            text=token_str,
                            prob=float(prob),
                        )
                    )
                blocks.append(
                    SpeechBlock(
                        start=Decimal(t0 / 1000),
                        end=Decimal(t1 / 1000),
                        text=text.decode("utf-8", errors="replace").strip() if isinstance(text, bytes) else text.strip(),
                        words=words,
                    )
                )
            else:
                blocks.append(
                    SentenceBlock(
                        start=Decimal(t0 / 1000),
                        end=Decimal(t1 / 1000),
                        text=text.decode("utf-8", errors="replace").strip() if isinstance(text, bytes) else text.strip(),
                    )
                )

            if bar is not None:
                bar()

    if not extract_words:
        blocks = _merge_short_segments(blocks)
        blocks = _split_long_segments(blocks)

    return blocks


def detect_words(
    media: Path,
    channels: Optional[Iterable[int]] = None,
    model_name="tiny.en",
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
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(tmp_file.name),
            ]
            run(cmd, stderr=DEVNULL, stdout=DEVNULL, check=True)

            audio_path = Path(tmp_file.name)
        else:
            audio_path = media.expanduser()

        _preload_whisper_libs()

        from pywhispercpp.model import ContextParams, Model

        cp = ContextParams(use_gpu=_GPU, gpu_device=0, flash_attn=True)
        model = Model(model_name, n_threads=4, context_params=cp)

        with wave.open(str(audio_path), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            sr = wf.getframerate()

        with alive_bar(title=f"Transcribing {media.name}") as bar:
            blocks = _transcribe_chunks(
                audio, model, sr=sr, extract_words=True, bar=bar
            )

        return blocks

    finally:
        if tmp_file is not None:
            tmp_file.close()
            tmp_file.delete = True


def _gpu_available() -> bool:
    """Check if the Vulkan GPU backend is available."""
    import importlib.util

    spec = importlib.util.find_spec("pywhispercpp")
    if not spec:
        return False
    site = Path(spec.origin).parent.parent
    return (site / "libggml-vulkan.so.0").exists()


def _preload_whisper_libs() -> None:
    """Pre-load whisper.cpp shared libs whose RUNPATH points to stale build dirs."""
    import ctypes
    import importlib.util
    import sys

    # Add the persistent shared build dir to the module search path so that
    # all nox sessions (which each have their own venv) can find the
    # one-time GPU build installed by noxfile.py's _ensure_whisper().
    whisper_site = Path.home() / ".cache" / "yt-automation" / "whisper-site"
    if whisper_site.exists():
        sys.path.insert(0, str(whisper_site))

    spec = importlib.util.find_spec("pywhispercpp")
    if spec:
        site = Path(spec.origin).parent.parent
        for lib in (
            "libggml-base.so.0",
            "libggml-cpu.so.0",
            "libggml-vulkan.so.0",
            "libggml.so.0",
            "libwhisper.so.1",
        ):
            p = site / lib
            if p.exists():
                ctypes.CDLL(str(p), mode=ctypes.RTLD_GLOBAL)


_GPU = _gpu_available()


def _default_model() -> str:
    return "large-v3-turbo" if _GPU else "tiny.en"


def _diff_transcriptions(
    primary: list[SpeechBlock],
    secondary: list[SpeechBlock],
) -> dict[int, tuple[str, float]]:
    """Align word streams from two models and flag divergences.

    Uses difflib word-sequence matching, distributing secondary words
    proportionally across primary words in replace blocks.

    Returns a dict mapping ``id(word) -> (secondary_text, secondary_confidence)``
    for words where the two transcriptions disagree.
    """
    from difflib import SequenceMatcher

    p_words: list[WordBlock] = []
    for seg in primary:
        if seg.words:
            p_words.extend(seg.words)

    s_flat: list[WordBlock] = []
    for seg in secondary:
        if seg.words:
            s_flat.extend(seg.words)

    if not p_words or not s_flat:
        return {}

    def _norm(w: WordBlock) -> str:
        return w.text.lower().strip(".,!?;:\"'()[]-—–")

    p_seq = [_norm(w) for w in p_words]
    s_seq = [_norm(w) for w in s_flat]

    matcher = SequenceMatcher(None, p_seq, s_seq)

    divergences: dict[int, tuple[str, float]] = {}
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        n_p = i2 - i1
        n_s = j2 - j1
        for k, idx in enumerate(range(i1, i2)):
            if n_s > 0 and op == "replace":
                s_start = j1 + int(k * n_s / n_p)
                s_end = j1 + int((k + 1) * n_s / n_p)
                s_words = s_flat[s_start:s_end]
                s_text = " ".join(w.text for w in s_words).strip()
                s_conf = max(w.prob for w in s_words) if s_words else 0.0
            else:
                s_text = ""
                s_conf = 0.0
            divergences[id(p_words[idx])] = (s_text, s_conf)

    return divergences


def _write_review(
    entries: list,
    media: Path,
    srt_path: Path,
    threshold: float = 0.5,
    model_name: str = "",
    divergences: dict[int, tuple[str, float]] | None = None,
) -> None:
    """Write a review file listing low-confidence words with playback commands."""
    import sys
    review_path = srt_path.with_suffix(".review.txt")
    lines: list[str] = [
        f"Review file for: {media.name}",
        f"Low-confidence threshold: {threshold}",
        "Words below this confidence are flagged. Use the ffplay command to hear context.",
    ]
    if divergences is not None:
        lines.append(
            "Two-pass divergence detection enabled — words where the two models"
            " disagree are also flagged."
        )
    lines.append("")

    n_flagged = 0
    n_divergent = 0
    for seg in entries:
        if not hasattr(seg, "words") or not seg.words:
            continue
        for w in seg.words:
            if w.prob < threshold:
                n_flagged += 1
                if divergences is not None and id(w) in divergences:
                    n_divergent += 1

    if n_flagged == 0:
        lines.append("No words below the confidence threshold.")
        if divergences is not None:
            lines.append("(No divergences between the two model passes.)")
        review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sys.stderr.write(f"Wrote {review_path} (no issues)\n")
        return
    elif divergences is not None and n_divergent == 0:
        lines.append(
            f"Note: all {n_flagged} low-confidence word(s) matched between"
            " both models — likely just noisy audio, not foreign terms."
        )
        lines.append("")

    for seg in entries:
        if not hasattr(seg, "words") or not seg.words:
            continue
        low = [w for w in seg.words if w.prob < threshold]
        if not low:
            continue
        lines.append(f"--- [{format_time(seg.start)} - {format_time(seg.end)}] ---")
        lines.append(f"    {seg.text}")
        for w in low:
            dur = max(float(w.end - w.start), 0.5)
            cmd = (
                f"ffplay -ss {w.start} -t {dur:.1f} -i '{media}' -nodisp -autoexit 2>/dev/null"
            )
            annotation = f"'{w.text}' (conf: {w.prob:.2f})"
            if divergences is not None and id(w) in divergences:
                s_text, s_conf = divergences[id(w)]
                if s_text:
                    annotation += f"  ← secondary: \"{s_text}\" ({s_conf:.0%} conf)"
                else:
                    annotation += "  ← (not in secondary output)"
            lines.append(f"  [{format_time(w.start)}] {annotation}")
            lines.append(f"    $ {cmd}")
        lines.append("")

    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stderr.write(f"Wrote {review_path}\n")


def _auto_correct(
    entries: list[SpeechBlock],
    divergences: dict[int, tuple[str, float]],
    primary_threshold: float,
    secondary_threshold: float = 0.95,
) -> dict[int, str]:
    """Auto-substitute words where the secondary model is highly confident.

    Returns a dict mapping ``id(word) -> corrected_text`` for primary words
    that diverged from the secondary model AND the secondary model's
    confidence is at or above *secondary_threshold* while the primary's
    is below *primary_threshold*.
    """
    corrections: dict[int, str] = {}
    for seg in entries:
        if not hasattr(seg, "words") or not seg.words:
            continue
        for w in seg.words:
            wid = id(w)
            if wid not in divergences:
                continue
            s_text, s_conf = divergences[wid]
            if not s_text:
                continue
            if w.prob < primary_threshold and s_conf >= secondary_threshold:
                corrections[wid] = s_text
    return corrections


def _interactive_fix(
    entries: list,
    media: Path,
    divergences: dict[int, tuple[str, float]] | None,
    primary_threshold: float,
    seg_text_overrides: dict[int, str],
) -> None:
    """Step through flagged segments, play audio, prompt for full text correction.

    Mutates *seg_text_overrides* in-place: ``{id(seg): corrected_text}``.
    """
    import subprocess
    import sys

    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    segments: list[SpeechBlock] = []
    for seg in entries:
        if not hasattr(seg, "words") or not seg.words:
            continue
        if id(seg) in seg_text_overrides:
            continue
        for w in seg.words:
            wid = id(w)
            if w.prob < primary_threshold:
                segments.append(seg)
                break
            if divergences is not None and wid in divergences:
                s_text, _ = divergences[wid]
                if s_text:
                    segments.append(seg)
                    break

    if not segments:
        console.print("[dim]No segments need review.[/dim]")
        return

    for seg in segments:
        table = Table(title=None, show_header=False, box=None, padding=(0, 1))
        table.add_column(style="bold")
        for w in seg.words:
            wid = id(w)
            flagged = w.prob < primary_threshold or (
                divergences is not None
                and wid in divergences
                and divergences[wid][0]
            )
            if not flagged:
                continue
            conf_color = "red" if w.prob < 0.5 else "yellow" if w.prob < 0.8 else "green"
            label = f"[{conf_color}]{w.text}[/{conf_color}] (conf: {w.prob:.2f})"
            if divergences is not None and wid in divergences:
                s_text, s_conf = divergences[wid]
                if s_text:
                    label += f"  ← [cyan]\"{s_text}\"[/cyan] ({s_conf:.0%} conf)"
            table.add_row(label)
        console.print()
        console.print(
            Panel(
                seg.text.strip(),
                title=f"[bold]{format_time(seg.start)}[/bold]  —  [bold]{format_time(seg.end)}[/bold]",
                border_style="dim",
            )
        )
        if table.row_count:
            console.print(table)

        seg_dur = float(seg.end - seg.start) + 0.6
        seg_start = max(0.0, float(seg.start) - 0.3)
        subprocess.run(
            ["ffplay", "-ss", f"{seg_start:.2f}", "-t", f"{seg_dur:.1f}",
             "-i", str(media), "-nodisp", "-autoexit"],
            stdout=DEVNULL, stderr=DEVNULL,
        )

        import questionary
        result = questionary.text(
            "Edit transcription (Enter to keep):",
            default=seg.text.strip(),
        ).ask()
        if result is None:
            break
        result = result.strip()
        if result.lower() in ("q", "quit"):
            break
        if result.lower() in ("s", "skip"):
            continue
        if result == seg.text.strip():
            continue
        seg_text_overrides[id(seg)] = result


def transcribe(args: Namespace) -> int:
    """Transcribe a video/audio file or directory to SRT captions."""
    import sys
    from tempfile import NamedTemporaryFile

    model_name = args.model if args.model != "default" else _default_model()
    language = getattr(args, "language", None)

    if language and model_name.endswith(".en"):
        model_name = model_name[:-3]
        sys.stderr.write(
            f"Language '{language}' specified, using multilingual model '{model_name}'\n"
        )

    sys.stderr.write(
        f"Backend: {'GPU (Vulkan)' if _GPU else 'CPU'}  Model: {model_name}\n"
    )

    _preload_whisper_libs()
    from pywhispercpp.model import ContextParams, Model

    sys.stderr.write("Loading model ...\n")
    cp = ContextParams(use_gpu=_GPU, gpu_device=0, flash_attn=True)
    model = Model(model_name, n_threads=4, context_params=cp)

    confidence_threshold = getattr(args, "confidence_threshold", None)
    second_model_name = mname if (mname := getattr(args, "second_model", None)) and mname.lower() != "none" else None
    do_review = getattr(args, "review", False) or second_model_name is not None
    needs_words = confidence_threshold is not None or do_review or second_model_name is not None

    dir_path = getattr(args, "dir", None)
    if dir_path:
        media_files = sorted(
            p for p in Path(dir_path).expanduser().iterdir()
            if p.suffix.lower() in MEDIA_EXTENSIONS
        )
        if not media_files:
            sys.stderr.write(f"No media files found in {dir_path}\n")
            return 1
    elif args.media:
        media_files = [args.media.expanduser()]
    else:
        sys.stderr.write("Specify a media file or use --dir for bulk mode\n")
        return 1

    for media in media_files:
        output = args.output or media.with_suffix(".srt")
        if output.exists() and not getattr(args, "force", False):
            sys.stderr.write(f"Skipping {media.name} ({output} exists)\n")
            continue

        sys.stderr.write(f"\n--- {media.name} ---\n")
        tmp = NamedTemporaryFile(suffix=".wav")
        cmd = [
            "ffmpeg", "-y", "-i", str(media),
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp.name),
        ]
        run(cmd, stderr=DEVNULL, stdout=DEVNULL, check=True)

        with wave.open(str(tmp.name), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            sr = wf.getframerate()

        divergences: dict = {}
        if second_model_name:
            sys.stderr.write(f"Loading second model {second_model_name} ...\n")
            cp2 = ContextParams(use_gpu=_GPU, gpu_device=0, flash_attn=True)
            second_model = Model(second_model_name, n_threads=4, context_params=cp2)

            from concurrent.futures import ThreadPoolExecutor
            sys.stderr.write("Running parallel models (primary + secondary)...\n")
            with ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(
                    _transcribe_chunks, audio, model, sr=sr,
                    extract_words=needs_words, bar=None, language=language,
                )
                f2 = pool.submit(
                    _transcribe_chunks, audio, second_model, sr=sr,
                    extract_words=True, bar=None, language=language,
                )
                entries = f1.result()
                second_entries = f2.result()
            sys.stderr.write("Parallel transcription complete — diffing...\n")
            divergences = _diff_transcriptions(entries, second_entries)
        else:
            with alive_bar(unknown="waves", title="Transcribing") as bar:
                entries = _transcribe_chunks(
                    audio, model, sr=sr, extract_words=needs_words, bar=bar, language=language
                )

        corrections: dict[int, str] = {}
        seg_text_overrides: dict[int, str] = {}
        if divergences:
            corrections = _auto_correct(
                entries,
                divergences,
                primary_threshold=confidence_threshold or 0.8,
                secondary_threshold=getattr(args, "auto_correct_threshold", 0.95),
            )

        if getattr(args, "interactive", False) and needs_words:
            _interactive_fix(
                entries,
                media,
                divergences or None,
                confidence_threshold or 0.8,
                seg_text_overrides,
            )

        srt_text = _format_srt(
            entries,
            confidence_threshold=confidence_threshold,
            corrections=corrections or None,
            seg_text_overrides=seg_text_overrides or None,
        )
        output.write_text(srt_text, encoding="utf-8")
        if corrections:
            sys.stderr.write(f"  Auto-corrected {len(corrections)} word(s).\n")
        if seg_text_overrides:
            sys.stderr.write(f"  Manually corrected {len(seg_text_overrides)} segment(s).\n")
        sys.stderr.write(f"Wrote {output} ({len(entries)} segments)\n")

        if do_review and needs_words:
            _write_review(
                entries,
                media,
                output,
                confidence_threshold or 0.5,
                model_name=model_name,
                divergences=divergences or None,
            )

    return 0


MEDIA_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wav", ".mp3", ".flac", ".m4a", ".ogg"}


def _format_srt(
    segments: list[SpeechBlock] | list[SentenceBlock],
    confidence_threshold: float | None = None,
    corrections: dict[int, str] | None = None,
    seg_text_overrides: dict[int, str] | None = None,
) -> str:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(
            f"{format_time(seg.start).replace('.', ',')} --> {format_time(seg.end).replace('.', ',')}"
        )
        if seg_text_overrides and id(seg) in seg_text_overrides:
            text = seg_text_overrides[id(seg)]
        else:
            text = seg.text.strip()
            if corrections and hasattr(seg, "words") and seg.words:
                for w in seg.words:
                    wid = id(w)
                    if wid in corrections:
                        stripped = w.text.rstrip(".,!?;:\"'")
                        punct = w.text[len(stripped):]
                        correction = corrections[wid].rstrip(".,!?;:\"'") + punct
                        text = text.replace(w.text, correction, 1)
        if confidence_threshold is not None and hasattr(seg, "words") and seg.words:
            low_conf = [w for w in seg.words if w.prob < confidence_threshold]
            if low_conf:
                notes = "; ".join(
                    f"{w.text}? (conf: {w.prob:.2f})" for w in low_conf
                )
                lines.append(f"; LOW CONF: {notes}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


FILLER_WORDS = frozenset(
    {
        "um",
        "umm",
        "uhh",
        "uh",
        "ahh",
        "ah",
        "erm",
        "er",
        "hmm",
        "mm",
        "mhm",
    }
)

DISCOURSE_MARKERS = frozenset(
    {
        "like",
        "actually",
        "basically",
        "literally",
        "honestly",
    }
)

DISCOURSE_PHRASES = frozenset(
    {
        ("you", "know"),
        ("i", "mean"),
        ("sort", "of"),
        ("kind", "of"),
        ("you", "see"),
    }
)


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
    for i in range(len(words) - 1):
        w0 = words[i].text.lower().strip(".,!?;:\"'()[]{}")
        w1 = words[i + 1].text.lower().strip(".,!?;:\"'()[]{}")
        if w0 == w1:
            found.append(SilenceBlock(start=words[i].start, end=words[i + 1].end))
    for i in range(len(words) - 2):
        w0 = words[i].text.lower().strip(".,!?;:\"'()[]{}")
        w1 = words[i + 1].text.lower().strip(".,!?;:\"'()[]{}")
        w2 = words[i + 2].text.lower().strip(".,!?;:\"'()[]{}")
        if w0 == w2 and w1 in filler_set:
            start = words[i].start
            end = words[i + 1].end
            found.append(SilenceBlock(start=start, end=end))
    return merge_regions(found, padding=Decimal(0))


def detect_discourse_markers(
    words: list[WordBlock],
    marker_set: set[str] = DISCOURSE_MARKERS,
    phrase_set: set[tuple[str, str]] = DISCOURSE_PHRASES,
) -> list[SilenceBlock]:
    found: list[SilenceBlock] = []
    for w in words:
        clean = w.text.lower().strip(".,!?;:\"'()[]{}")
        if clean in marker_set:
            found.append(SilenceBlock(start=w.start, end=w.end))
    for i in range(len(words) - 1):
        w0 = words[i].text.lower().strip(".,!?;:\"'()[]{}")
        w1 = words[i + 1].text.lower().strip(".,!?;:\"'()[]{}")
        if (w0, w1) in phrase_set:
            found.append(SilenceBlock(start=words[i].start, end=words[i + 1].end))
    return merge_regions(found, padding=Decimal(0))


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
    media_discourse: dict[Path, list[SilenceBlock]] | None = None,
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
                + (media_discourse.get(media_path, []) if media_discourse else [])
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
            shotcut.cut_from_track(track, time=region.start, duration=region.duration)

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

    mode = getattr(args, "mode", "standard")
    filler_set = set(FILLER_WORDS)
    if args.filler_words:
        filler_set.update(w.strip().lower() for w in args.filler_words.split(","))

    padding = Decimal(str(getattr(args, "padding", "0.1")))
    model = getattr(args, "model", "default")
    if model == "default":
        model = _default_model()

    media_silences = _media_silence_regions(
        sc, track_indices, channels, threshold_db, min_silence, max_silence
    )

    if mode == "basic":
        cut_regions = _timeline_cut_regions(
            sc,
            track_indices,
            media_silences,
            media_fillers={},
            media_repairs={},
            media_discourse={},
            padding=padding,
        )
        _apply_cuts(sc, cut_regions)
        output_path = args.output or project_path
        sc.save(Path(output_path).expanduser())
        return 0

    import sys
    media_fillers: dict[Path, list[SilenceBlock]] = {}
    media_repairs: dict[Path, list[SilenceBlock]] = {}
    media_discourse: dict[Path, list[SilenceBlock]] = {}
    for media_path in media_silences:
        words = detect_words(media=media_path, channels=channels, model_name=model)
        all_word_blocks = [w for seg in words for w in seg.words]
        media_fillers[media_path] = detect_fillers(all_word_blocks, filler_set)
        if mode in ("full",):
            media_repairs[media_path] = detect_self_repairs(all_word_blocks, filler_set)
            media_discourse[media_path] = detect_discourse_markers(all_word_blocks)
            n_rep = len(media_repairs[media_path])
            n_disc = len(media_discourse[media_path])
            if n_rep or n_disc:
                sys.stderr.write(
                    f"  {media_path.name}: {n_rep} repair(s), {n_disc} discourse marker(s)\n"
                )

    cut_regions = _timeline_cut_regions(
        sc,
        track_indices,
        media_silences,
        media_fillers,
        media_repairs,
        media_discourse,
        padding=padding,
    )

    _apply_cuts(sc, cut_regions)

    output_path = args.output or project_path
    sc.save(Path(output_path).expanduser())
    return 0
