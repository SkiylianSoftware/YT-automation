from logging import getLogger
import logging.config
import sys
from argparse import ArgumentParser
from pathlib import Path

from .playlist_automation import playlist_automation
from .youtube import YouTube

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
                "filename": "application.log",
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

LOG = getLogger("main")

def main() -> int:
    parser = ArgumentParser(description="YouTube Automation scripts")

    # Shared arguments come before sub-command arguments
    parser.add_argument(
        "--env-client",
        type=Path,
        default=Path(".env.client"),
        help="Filepath for the youtube client credentials",
    )
    parser.add_argument(
        "--env-token",
        type=Path,
        default=Path(".env.token"),
        help="Filepath for the youtube access_token",
    )

    subcommands = parser.add_subparsers(help="sub-command help")

    # Playlist automation

    playlist_parser = subcommands.add_parser("playlist-automation")
    playlist_parser.set_defaults(func=playlist_automation)

    # Parse arguments and execute
    args = parser.parse_args()
    if func := getattr(args, "func", None):
        try:
            yt = YouTube(client_env=args.env_client, token_env=args.env_token)
            yt.authenticate()
        except Exception as e:
            LOG.error("Could not authenticate to YouTube")
            LOG.error(e)
        LOG.info(f"Running entrypoint {func.__name__}")
        return func(yt)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
