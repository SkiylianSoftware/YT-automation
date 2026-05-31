"""Main entrypoint to YouTube Automation."""

import importlib
import logging.config
import sys
from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path


def _lazy(mod_name: str, attr: str):
    """Import *attr* from *mod_name* only when called."""

    def wrapper(*args, **kwargs):
        mod = importlib.import_module(f".{mod_name}", package=__package__)
        return getattr(mod, attr)(*args, **kwargs)

    return wrapper


WHISPER_MODELS = [
    "default",
    "tiny.en",
    "tiny",
    "base.en",
    "base",
    "small.en",
    "small",
    "medium.en",
    "medium",
    "large-v3",
    "large-v3-turbo",
]


def setup_parser() -> ArgumentParser:
    """Configure parser arguments."""
    is_nox = "nox" in sys.orig_argv[0]
    parser = ArgumentParser(
        description="YouTube Automation scripts", prog="nox --" if is_nox else __name__
    )

    # Shared arguments come before sub-command arguments
    parser.add_argument(
        "--logging-path",
        type=Path,
        default=Path("application.log"),
        help="Filepath for the output log.",
    )
    parser.add_argument(
        "--append-log",
        action="store_true",
        help="If set, append to the end of the log rather than"
        "clearing at each execution",
    )

    subcommands = parser.add_subparsers(help="sub-command help")

    # Legacy Updater
    updater_parser = subcommands.add_parser("legacy-updater", aliases=["update-titles"])
    updater_parser.add_argument(
        "--env-youtube",
        type=Path,
        default=Path(".env.youtube"),
        help="Filepath for the youtube credentials",
    )
    updater_parser.add_argument(
        "--commit",
        action="store_true",
        help="If set, actually pushes the title updates to the YouTube API. Otherwise performs a Dry Run.",
    )
    updater_parser.set_defaults(func=_lazy("legacy_updater", "legacy_update"))

    # Playlist automation

    playlist_parser = subcommands.add_parser(
        "playlist-automation", aliases=["playlist"]
    )
    playlist_parser.add_argument(
        "--env-youtube",
        type=Path,
        default=Path(".env.youtube"),
        help="Filepath for the youtube credentials",
    )
    playlist_parser.set_defaults(
        func=_lazy("playlist_automation", "playlist_automation")
    )

    # Calendar automation
    calendar_parser = subcommands.add_parser(
        "calendar-automation", aliases=["calendar"]
    )
    calendar_parser.set_defaults(
        func=_lazy("calendar_automation", "calendar_automation")
    )
    calendar_parser.add_argument(
        "--env-youtube",
        type=Path,
        default=Path(".env.youtube"),
        help="Filepath for the youtube credentials",
    )
    calendar_parser.add_argument(
        "--env-calendar",
        type=Path,
        default=Path(".env.calendar"),
        help="Filepath for the calendar credentials",
    )
    calendar_parser.add_argument(
        "--timezone",
        type=str,
        default="UTC",
        help="Timezone to use if creating new calendars, or adding events to calendars",
    )

    # Re-auth endpoint inherits from essentially all parsers.
    _lazy("run_all", "add_combined")(
        subcommands,
        "playlist-automation",
        "calendar-automation",
        name="reauth-clients",
        aliases="reauth",
        function=_lazy("re_auth", "re_auth"),
    )

    # Background music automation
    music_parser = subcommands.add_parser("background-music", aliases=["music"])
    music_project = music_parser.add_mutually_exclusive_group(required=True)
    music_project.add_argument(
        "--project",
        type=Path,
        help="Filepath of the shotcut project to parse",
    )
    music_project.add_argument(
        "--project-path",
        type=Path,
        help="Filepath of the shotcut projects folder to search "
        "for the modified latest entry",
    )
    music_parser.add_argument(
        "--music",
        type=Path,
        nargs="+",
        help="Filepath of the music folder background songs are stored in",
    )
    music_parser.add_argument(
        "--min-gap",
        type=int,
        default=0,
        help="Minimum gap required to be left between background music tracks",
    )
    music_parser.add_argument(
        "--max-gap",
        type=int,
        default=10,
        help="Maximum gap that can be left between background music tracks",
    )
    music_parser.add_argument(
        "--gain",
        type=int,
        default=-25,
        help="The gain to apply to the background music track by default",
    )
    music_parser.add_argument(
        "--track-name",
        type=str,
        default="Music",
        help="The name of the video track that background music will be added to.",
    )
    music_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Exit the program without writing changes to disk;"
        " used to view what song choices would be made.",
    )
    music_parser.set_defaults(func=_lazy("background_music", "background_music"))

    # Silence removal
    silence_parser = subcommands.add_parser("silence-removal", aliases=["silence"])
    silence_parser.add_argument(
        "project",
        type=Path,
        help="Filepath of the Shotcut project to edit",
    )
    silence_parser.add_argument(
        "--tracks",
        type=str,
        nargs="+",
        default=["1"],
        help="Track indices or names to edit (default: 1)",
    )
    silence_parser.add_argument(
        "--streams",
        type=str,
        nargs="+",
        default=None,
        help="OBS audio stream indices to analyse (e.g. 3 for mic)",
    )
    silence_parser.add_argument(
        "--silence-threshold",
        type=int,
        default=-40,
        help="Silence detection threshold in dB (default: -40)",
    )
    silence_parser.add_argument(
        "--silence-min-duration",
        type=float,
        default=0.15,
        help="Minimum silence duration in seconds (default: 0.15)",
    )
    silence_parser.add_argument(
        "--max-silence",
        type=float,
        default=None,
        help="Ignore silences longer than this many seconds",
    )
    silence_parser.add_argument(
        "--filler-words",
        type=str,
        default=None,
        help="Comma-separated extra filler words to detect",
    )
    silence_parser.add_argument(
        "--padding",
        type=float,
        default=0.1,
        help="Padding around cut regions in seconds (default: 0.1)",
    )
    silence_parser.add_argument(
        "--model",
        type=str,
        default="default",
        choices=WHISPER_MODELS,
        help="Whisper model name (default: large-v3-turbo if GPU, tiny.en if CPU)",
    )
    silence_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for the edited project (default: overwrite input)",
    )
    silence_parser.set_defaults(func=_lazy("silence", "silence_removal"))

    # Transcribe
    transcribe_parser = subcommands.add_parser("transcribe", aliases=["captions"])
    transcribe_parser.add_argument(
        "media",
        type=Path,
        help="Filepath of the video/audio to transcribe",
    )
    transcribe_parser.add_argument(
        "--model",
        type=str,
        default="default",
        choices=WHISPER_MODELS,
        help="Whisper model name (default: medium.en if GPU, tiny.en if CPU)",
    )
    transcribe_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output SRT file path (default: <media>.srt)",
    )
    transcribe_parser.set_defaults(func=_lazy("silence", "transcribe"))

    _lazy("run_all", "add_combined")(
        subcommands,
        "playlist-automation",
        "calendar-automation",
        name="all-automation",
        aliases=["everything", "all"],
        function=_lazy("run_all", "run_all"),
    )

    return parser


def main() -> int:
    """Entrypoint for the whole program."""
    LOG = getLogger("main")
    log = LOG.getChild("entry")

    parser = setup_parser()
    args = parser.parse_args()

    # configure logging

    logging.config.dictConfig(
        {
            "version": 1,
            "formatters": {
                "default": {"format": "%(name)s: %(message)s"},
                "file": {"format": "[%(asctime)s] %(name)s: %(message)s"},
            },
            "handlers": {
                "file": {
                    "class": "logging.FileHandler",
                    "level": "DEBUG",
                    "formatter": "file",
                    "filename": args.logging_path,
                    "mode": "a" if args.append_log else "w",
                },
                "stream": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {"level": "DEBUG", "handlers": ["file", "stream"]},
        }
    )

    # authenticate to youtube and run the requested entrypoint

    if func := getattr(args, "func", None):
        # A lot of scripts inherit the youtube environment
        if yt := getattr(args, "env_youtube", None):
            try:
                yt = _lazy("youtube", "YouTube")(youtube_env=yt)
                yt.authenticate()
            except Exception as e:
                log.error("Could not authenticate to YouTube")
                raise e

            log.info(f"Running entrypoint {func.__name__}")
            return func(args, yt)

        # but not all of them do
        else:
            return func(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
