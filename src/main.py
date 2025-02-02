from __future__ import annotations

import logging
import re
from pathlib import Path

from pyyoutube import Playlist, Video

from .youtube import YouTube

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s", filename="application.log"
)

PLAYLIST_REGEX = re.compile(r"(:?(?P<series>[^\-]+)\- )?(?P<category>.*)")
VIDEO_REGEX = re.compile(
    r"(?P<category>[^:]+)(:?: (?P<series>[^#]+))?#(?P<ep_number>\d+) \- (?P<title>.*)"
)


def game_to_short(game_name: str) -> str:
    """Kerbal Space Program -> KSP"""
    """KSP -> KSP"""
    if all(s.isupper() for s in game_name):
        return game_name
    return "".join(word[0].upper() for word in game_name.split())


def playlist_mapping(playlists: list[Playlist]) -> dict[str, dict[str, Playlist]]:
    """
    Returns: {GAME_ACRONYM: [Series_for_game, ...], ...}
    """
    mapping: dict[str, dict[str, Playlist]] = {}
    for playlist in playlists:
        if search := PLAYLIST_REGEX.search(playlist.snippet.title):
            category: str = search.group("category").strip()
            series: str = str(search.group("series")).strip()
            shorthand = game_to_short(category)

            if shorthand not in mapping:
                mapping[shorthand] = {}

            mapping[shorthand][series] = playlist

    return mapping


def video_mapping(videos: list[Video]) -> dict[str, dict[str, list[Video]]]:
    """
    Returns: {GAME_ACRONYM: {Series_for_game: [videos_for_series, ...], ...}, ...}
    """
    mapping: dict[str, dict[str, list[Video]]] = {}
    for video in videos:
        if search := VIDEO_REGEX.search(video.snippet.title):
            category: str = search.group("category").strip()
            series: str = str(search.group("series")).strip()
            shorthand = game_to_short(category)

            if shorthand not in mapping.keys():
                mapping[shorthand] = {}
            if series not in mapping[shorthand].keys():
                mapping[shorthand][series] = []

            mapping[shorthand][series].append(video)

    return mapping


def find_videos_not_in_playlists(
    yt: YouTube,
    playlists: dict[str, dict[str, Playlist]],
    videos: dict[str, dict[str, list[Video]]],
) -> list[tuple[Video, Playlist]]:
    """
    Returns: [(video, playlist_for_video), ...]
    """
    missing: list[tuple[Video, Playlist]] = []
    for game, serieses in videos.items():
        for series, vids in serieses.items():
            if pl := playlists.get(game, {}).get(series, {}):
                pl_vids = yt.playlist_videos(pl.id)
                pl_ids = [pl_vid.id for pl_vid in pl_vids]
                for vid in vids:
                    if vid.id not in pl_ids:
                        missing.append((vid, pl))

    return missing


def add_video_to_playlists(
    yt: YouTube, missing_vids: list[tuple[Video, Playlist]]
) -> None:
    for video, playlist in missing_vids:
        try:
            yt.add_to_playlist(playlist, video)
            logging.debug(
                f"Successfully added {video.snippet.title} to {playlist.snippet.title}!"
            )
        except Exception as e:
            logging.error(
                f"Failed to add {video.snippet.title} to {playlist.snippet.title}"
            )
            logging.error(e)


def main() -> int:
    yt = YouTube(client_env=Path(".env.client"), token_env=Path(".env.token"))
    yt.authenticate()

    client = yt.client
    logging.debug(f"Logged in with {client}")

    # Fetch channel
    channel = yt.me
    logging.debug(f"Found channel: {channel.brandingSettings.channel.title}")

    # Fetch playlists
    channel_playlists = yt.playlists
    logging.debug(f"Found playlists: {yt.show(channel_playlists)}")

    # Create playlist mapping
    playlists = playlist_mapping(channel_playlists)
    logging.debug(f"Playlist mapping: {playlists}")

    # Fetch uploads
    channel_videos = yt.public_videos
    logging.debug(f"Found videos: {yt.show(channel_videos)}")

    # create video mapping
    videos = video_mapping(channel_videos)
    logging.debug(f"Video mapping: {videos}")

    # check all videos are in the correct playlists
    missing_from_playlists = find_videos_not_in_playlists(yt, playlists, videos)

    # add video to playlist if missing
    if missing_from_playlists:
        add_video_to_playlists(yt, missing_from_playlists)
    else:
        logging.info("No videos are missing from their respective playlists!")

    return 0


if __name__ == "__main__":
    quit(main())
