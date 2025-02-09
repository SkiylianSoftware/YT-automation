"""Main entrypoint to YouTube Automation."""

import logging.config
import sys
from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path

from .calendar_automation import calendar_automation
from .playlist_automation import playlist_automation
from .API.youtube import YouTube
from .video_upload import upload_video


def setup_parser() -> ArgumentParser:
    """Configure parser arguments."""
    is_nox = "nox" in sys.orig_argv[0]
    parser = ArgumentParser(
        description="YouTube Automation scripts", prog="nox --" if is_nox else __name__
    )

    # Shared arguments come before sub-command arguments
    parser.add_argument(
        "--env-youtube",
        type=Path,
        default=Path(".env.youtube"),
        help="Filepath for the youtube credentials",
    )
    parser.add_argument(
        "--logging-path",
        type=Path,
        default=Path("application.log"),
        help="Filepath for the output log.",
    )

    subcommands = parser.add_subparsers(help="sub-command help")

    # Playlist automation

    playlist_parser = subcommands.add_parser("playlist-automation")
    playlist_parser.set_defaults(func=playlist_automation)

    # Calendar automation
    calendar_parser = subcommands.add_parser("calendar-automation")
    calendar_parser.set_defaults(func=calendar_automation)
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

    # Video upload
    upload_parser = subcommands.add_parser("upload-ui")
    upload_parser.set_defaults(func=upload_video)
    upload_parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("videos.db"),
        help="Filepath for the local DB store."
    )


    return parser


def main() -> int:
    """Entrypoint for the whole program."""
    LOG = getLogger("main")

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
                    "mode": "a",
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
        try:
            yt = YouTube(
                youtube_env=args.env_youtube
            )
            yt.authenticate()
        except Exception as e:
            LOG.error("Could not authenticate to YouTube")
            LOG.error(e)
        LOG.info(f"Running entrypoint {func.__name__}")
        return func(args, yt)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
