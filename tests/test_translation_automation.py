from types import SimpleNamespace
from unittest.mock import MagicMock

from src.translation_automation import (
    DEFAULT_KEEP,
    caption_label,
    disallowed_captions,
    is_allowed,
    render_report,
    strip_captions,
    strip_localizations,
    translation_automation,
)
from src.youtube import QuotaExceededError


def make_caption(language, track_kind="standard"):
    return SimpleNamespace(
        id=f"cap-{language}-{track_kind}",
        snippet=SimpleNamespace(language=language, trackKind=track_kind),
    )


def make_video(video_id="vid1", title="Test", default_language="en-GB"):
    return SimpleNamespace(
        id=video_id,
        snippet=SimpleNamespace(
            title=title,
            defaultLanguage=default_language,
            defaultAudioLanguage=None,
        ),
    )


def test_is_allowed_is_case_insensitive():
    assert is_allowed("en-GB", ["en-GB"])
    assert is_allowed("en-gb", ["en-GB"])
    assert not is_allowed("en-US", ["en-GB"])
    assert not is_allowed("en", ["en-GB"])
    assert not is_allowed(None, ["en-GB"])


def test_disallowed_captions_keeps_only_allowed():
    captions = [
        make_caption("en-GB", "standard"),
        make_caption("en", "ASR"),
        make_caption("nl-NL", "standard"),
        make_caption("en-US", "standard"),
    ]
    targets = disallowed_captions(captions, ["en-GB"])
    labels = {caption_label(c) for c in targets}
    assert labels == {"en (ASR)", "nl-NL (standard)", "en-US (standard)"}
    assert "en-GB (standard)" not in labels


def test_strip_localizations_removes_disallowed_only():
    yt = MagicMock()
    yt.video_localizations.return_value = {
        "en-GB": {"title": "keep"},
        "nl-NL": {"title": "drop"},
        "en-US": {"title": "drop"},
    }
    video = make_video()

    result = strip_localizations(yt, video, ["en-GB"], dry_run=False)

    assert result == ["en-US", "nl-NL"]
    # Only the allowed localization is written back.
    yt.set_video_localizations.assert_called_once_with(
        video, {"en-GB": {"title": "keep"}}
    )


def test_strip_localizations_noop_when_all_allowed():
    yt = MagicMock()
    yt.video_localizations.return_value = {"en-GB": {"title": "keep"}}
    video = make_video()

    result = strip_localizations(yt, video, ["en-GB"], dry_run=False)

    assert result == []
    yt.set_video_localizations.assert_not_called()


def test_strip_localizations_dry_run_makes_no_calls():
    yt = MagicMock()
    yt.video_localizations.return_value = {"nl-NL": {}, "de-DE": {}}
    video = make_video()

    result = strip_localizations(yt, video, ["en-GB"], dry_run=True)

    assert result == ["de-DE", "nl-NL"]
    yt.set_video_localizations.assert_not_called()


def test_strip_captions_records_failures():
    yt = MagicMock()
    yt.video_captions.return_value = [make_caption("nl-NL"), make_caption("de-DE")]
    yt.delete_caption.side_effect = [None, Exception("nope")]
    video = make_video()

    deleted, failed = strip_captions(yt, video, ["en-GB"], dry_run=False)

    assert deleted == ["nl-NL (standard)"]
    assert failed == ["de-DE (standard)"]


def test_render_report_lists_every_video():
    from src.translation_automation import VideoReport

    reports = [
        VideoReport(video=make_video("vid1", "First"), localizations=["nl-NL"]),
        VideoReport(video=make_video("vid2", "Second")),
    ]
    report = render_report(reports, "My Channel", ["en-GB"], dry_run=True)

    assert "My Channel" in report
    assert "en-GB" in report
    assert "vid1" in report
    assert "vid2" in report
    assert "dry-run" in report


def test_default_keep_is_en_gb():
    assert DEFAULT_KEEP == ["en-GB"]


def test_translation_automation_fails_without_videos():
    yt = MagicMock()
    yt.videos = []
    result = translation_automation(SimpleNamespace(), yt)
    assert result == 1


def test_translation_automation_succeeds(tmp_path):
    yt = MagicMock()
    yt.videos = [make_video("vid1", "First")]
    yt.channel_name = "My Channel"
    yt.video_localizations.return_value = {}
    yt.video_captions.return_value = []

    report_path = tmp_path / "report.md"
    args = SimpleNamespace(
        dry_run=True, report_path=report_path, keep_language=["en-GB"]
    )

    result = translation_automation(args, yt)

    assert result == 0
    assert report_path.exists()
    assert "First" in report_path.read_text()


def test_translation_automation_stops_on_quota(tmp_path):
    yt = MagicMock()
    yt.videos = [make_video("vid1", "First"), make_video("vid2", "Second")]
    yt.channel_name = "My Channel"
    yt.video_localizations.side_effect = QuotaExceededError("quota gone")

    report_path = tmp_path / "report.md"
    args = SimpleNamespace(
        dry_run=False, report_path=report_path, keep_language=["en-GB"]
    )

    result = translation_automation(args, yt)

    # Quota exhaustion is surfaced as a non-zero exit, and a partial audit
    # (zero completed videos here) is still written.
    assert result == 1
    assert report_path.exists()


def test_translation_automation_limit(tmp_path):
    yt = MagicMock()
    yt.videos = [make_video(f"vid{i}", f"Video {i}") for i in range(5)]
    yt.channel_name = "My Channel"
    yt.video_localizations.return_value = {}
    yt.video_captions.return_value = []

    report_path = tmp_path / "report.md"
    args = SimpleNamespace(
        dry_run=True,
        report_path=report_path,
        keep_language=["en-GB"],
        limit=2,
    )

    result = translation_automation(args, yt)

    assert result == 0
    # Only the first two videos are fetched for localizations.
    assert yt.video_localizations.call_count == 2
