"""Main entrypoint to YouTube Automation."""

import logging.config
import sys
from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path

from .background_music import background_music
from .calendar_automation import calendar_automation
from .playlist_automation import playlist_automation
from .re_auth import re_auth
from .run_all import add_combined, run_all
from .translation_automation import translation_automation
from .youtube import YouTube


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

    subcommands = parser.add_subparsers(
        title="commands", metavar="<command>", help="(aliases shown in parentheses)"
    )

    # Playlist automation

    playlist_parser = subcommands.add_parser(
        "playlist-automation",
        aliases=["playlist"],
        help="Add videos to their respective playlists based on title",
    )
    playlist_parser.add_argument(
        "--env-youtube",
        type=Path,
        default=Path(".env.youtube"),
        help="Filepath for the youtube credentials",
    )
    playlist_parser.set_defaults(func=playlist_automation)

    # Calendar automation
    calendar_parser = subcommands.add_parser(
        "calendar-automation",
        aliases=["calendar"],
        help="Sync released and upcoming videos into google calendars",
    )
    calendar_parser.set_defaults(func=calendar_automation)
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

    # Translation removal
    translation_parser = subcommands.add_parser(
        "translation-automation",
        aliases=["translations", "detranslate"],
        help="Strip auto-generated translations from every video",
    )
    translation_parser.add_argument(
        "--env-youtube",
        type=Path,
        default=Path(".env.youtube"),
        help="Filepath for the youtube credentials",
    )
    translation_parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("translation-audit.md"),
        help="Filepath for the audit report of remaining manual translations",
    )
    translation_parser.add_argument(
        "--keep-language",
        type=str,
        nargs="+",
        default=["en-GB"],
        help="Language tag(s) to keep; every other translation is removed "
        "(default: en-GB)",
    )
    translation_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N videos this run, to stay within the "
        "daily API quota; re-run later to continue",
    )
    translation_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be removed without writing any changes",
    )
    translation_parser.set_defaults(func=translation_automation)

    # Re-auth endpoint inherits from essentially all parsers.
    add_combined(
        subcommands,
        "playlist-automation",
        "calendar-automation",
        name="reauth-clients",
        aliases="reauth",
        function=re_auth,
        help="Re-authenticate to every external service",
    )

    # Background music automation
    music_parser = subcommands.add_parser(
        "background-music",
        aliases=["music"],
        help="Populate a shotcut project with random background music",
    )
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
    music_parser.set_defaults(func=background_music)

    add_combined(
        subcommands,
        "playlist-automation",
        "calendar-automation",
        "translation-automation",
        name="all-automation",
        aliases=["everything", "all"],
        function=run_all,
        help="Run every automation that targets external services",
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
                yt = YouTube(youtube_env=yt)  # type: ignore [call-arg]
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
