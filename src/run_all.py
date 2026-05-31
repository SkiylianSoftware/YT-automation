from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from logging import getLogger
from typing import TYPE_CHECKING, Callable
from .youtube import YouTube

LOG = getLogger("combined")


def add_combined(
    subcommands: _SubParsersAction,
    *targets: str,
    name: str,
    function: Callable[[Namespace, YouTube], int],
    aliases: str | list[str] = [],
) -> ArgumentParser:
    """Generate a subparser with the arguments of the provided set of target parsers."""
    combined_parser: ArgumentParser = subcommands.add_parser(
        name, aliases=[aliases] if isinstance(aliases, str) else aliases
    )

    # dynamically generate
    seen = {"help"}

    subparsers: list[ArgumentParser] = [subcommands.choices[t] for t in targets]
    for parser in subparsers:
        for action in parser._actions:
            if action.dest in seen:
                continue

            combined_parser._add_action(action)
            seen.add(action.dest)

    combined_parser.set_defaults(func=function)

    return combined_parser


def run_all(args: Namespace, yt: YouTube) -> int:
    """Entrypoint for running all of the external resource entrypoints."""
    from .calendar_automation import calendar_automation
    from .playlist_automation import playlist_automation

    LOG.info("Running calendar entrypoint")
    if calendar_automation(args=args, yt=yt):
        return 1

    LOG.info("Running playlist entrypoint")
    if playlist_automation(args=args, yt=yt):
        return 1

    LOG.info("Successfully executed all entrypoints")
    return 0
