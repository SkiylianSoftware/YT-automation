"""Strip YouTube's auto-generated translations from videos.

Only a subset of YouTube's auto-translation suite is reachable through the
Data API v3:

- Translated titles/descriptions (``localizations``) can be pruned down to an
  allowed set of languages.
- Auto-generated / disallowed caption tracks can sometimes be deleted.
- Auto-dubbed audio tracks and translated thumbnails have no API surface and
  can only be removed by hand in YouTube Studio. Every video is listed in an
  audit report with a Studio link so those can be cleaned up manually.

By default only ``en-GB`` is kept; every other language is treated as an
unwanted translation.
"""

from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass, field
from datetime import UTC, datetime
from logging import getLogger
from pathlib import Path

from pyyoutube import Caption, Video

from .youtube import QuotaExceededError, YouTube

LOG = getLogger("translation-automation")

STUDIO_URL = "https://studio.youtube.com/video/{video_id}/translations"

DEFAULT_KEEP = ["en-GB"]


@dataclass
class VideoReport:
    """Record of what was (or would be) removed from a single video."""

    video: Video
    localizations: list[str] = field(default_factory=list)
    deleted_captions: list[str] = field(default_factory=list)
    failed_captions: list[str] = field(default_factory=list)


def normalise(language: str | None) -> str:
    """Normalise a BCP-47 language tag for comparison."""
    return language.strip().lower() if language else ""


def is_allowed(language: str | None, keep: list[str]) -> bool:
    """Return whether a language tag is in the allowed keep list."""
    return normalise(language) in {normalise(k) for k in keep}


def caption_label(caption: Caption) -> str:
    """Human-readable identifier for a caption track."""
    snippet = caption.snippet
    return f"{snippet.language or '??'} ({snippet.trackKind or 'standard'})"


def disallowed_captions(captions: list[Caption], keep: list[str]) -> list[Caption]:
    """Return caption tracks whose language is not in the allowed keep list."""
    return [c for c in captions if not is_allowed(c.snippet.language, keep)]


def strip_localizations(
    yt: YouTube, video: Video, keep: list[str], dry_run: bool
) -> list[str]:
    """Prune localizations down to the allowed languages; return those removed."""
    log = LOG.getChild("localizations")
    localizations = yt.video_localizations(video.id)
    if not localizations:
        return []

    remove = sorted(lang for lang in localizations if not is_allowed(lang, keep))
    if not remove:
        return []

    kept = {
        lang: value for lang, value in localizations.items() if is_allowed(lang, keep)
    }
    title = video.snippet.title

    if dry_run:
        log.info(
            f"[dry-run] would remove {remove} from {title} "
            f"(keeping {sorted(kept) or 'none'})"
        )
        return remove

    try:
        yt.set_video_localizations(video, kept)
        log.info(f"Removed localizations {remove} from {title}")
    except QuotaExceededError:
        raise
    except Exception as e:
        log.error(f"Failed to remove localizations from {title}: {e}")
    return remove


def strip_captions(
    yt: YouTube, video: Video, keep: list[str], dry_run: bool
) -> tuple[list[str], list[str]]:
    """Delete disallowed caption tracks; return (deleted, failed) labels."""
    log = LOG.getChild("captions")
    captions = yt.video_captions(video.id)
    targets = disallowed_captions(captions, keep)

    deleted: list[str] = []
    failed: list[str] = []
    title = video.snippet.title

    for caption in targets:
        label = caption_label(caption)
        if dry_run:
            log.info(f"[dry-run] would delete caption {label} from {title}")
            deleted.append(label)
            continue
        try:
            yt.delete_caption(caption.id)
            log.info(f"Deleted caption {label} from {title}")
            deleted.append(label)
        except QuotaExceededError:
            raise
        except Exception as e:
            log.warning(f"Could not delete caption {label} from {title}: {e}")
            failed.append(label)

    return deleted, failed


def render_report(
    reports: list[VideoReport], channel_name: str, keep: list[str], dry_run: bool
) -> str:
    """Build the markdown audit report."""
    mode = "dry-run (no changes written)" if dry_run else "applied"
    lines = [
        f"# Translation audit for {channel_name}",
        "",
        f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} ({mode}).",
        f"Allowed languages: {', '.join(keep)}.",
        "",
        "The YouTube Data API cannot see or remove auto-dubbed audio tracks or "
        "translated thumbnails. Use the Studio link on each row to remove those "
        "by hand.",
        "",
        "| Video | Localizations removed | Captions removed | Captions failed |"
        " Manual (dubs/thumbnails) |",
        "|---|---|---|---|---|",
    ]
    for report in reports:
        studio = STUDIO_URL.format(video_id=report.video.id)
        title = report.video.snippet.title.replace("|", "\\|")
        lines.append(
            f"| [{title}]({studio}) "
            f"| {', '.join(report.localizations) or '-'} "
            f"| {', '.join(report.deleted_captions) or '-'} "
            f"| {', '.join(report.failed_captions) or '-'} "
            f"| [check in Studio]({studio}) |"
        )
    lines.append("")
    return "\n".join(lines)


def translation_automation(args: Namespace, yt: YouTube) -> int:
    """Entrypoint for translation removal."""
    log = LOG.getChild("translations")
    dry_run: bool = getattr(args, "dry_run", False)
    keep: list[str] = getattr(args, "keep_language", None) or DEFAULT_KEEP
    limit: int | None = getattr(args, "limit", None)

    try:
        videos = yt.videos
    except QuotaExceededError as e:
        log.error(str(e))
        return 1
    if not videos:
        log.error(f"No videos found for {yt.me}")
        return 1

    if limit:
        videos = videos[:limit]

    log.info(
        f"Processing {len(videos)} videos, keeping only {keep} "
        f"({'dry-run preview' if dry_run else 'applying changes'})"
    )

    reports: list[VideoReport] = []
    quota_hit = False
    for video in videos:
        try:
            localizations = strip_localizations(yt, video, keep, dry_run)
            deleted, failed = strip_captions(yt, video, keep, dry_run)
        except QuotaExceededError as e:
            log.error(str(e))
            log.warning(
                f"Stopped after {len(reports)}/{len(videos)} videos; "
                "re-run after the quota resets to continue."
            )
            quota_hit = True
            break
        reports.append(
            VideoReport(
                video=video,
                localizations=localizations,
                deleted_captions=deleted,
                failed_captions=failed,
            )
        )

    report_path: Path = getattr(args, "report_path", Path("translation-audit.md"))
    report_path.write_text(render_report(reports, yt.channel_name, keep, dry_run))
    log.info(f"Audit report written to {report_path}")

    total_loc = sum(len(r.localizations) for r in reports)
    total_caps = sum(len(r.deleted_captions) for r in reports)
    total_failed = sum(len(r.failed_captions) for r in reports)

    verb = "Would remove" if dry_run else "Removed"
    log.info(
        f"{verb} {total_loc} localization(s) and {total_caps} caption track(s) "
        f"across {len(reports)} videos."
    )
    if total_failed:
        log.warning(
            f"{total_failed} caption track(s) could not be deleted via the API; "
            "see the audit report to remove them in Studio."
        )

    return 1 if quota_hit else 0
