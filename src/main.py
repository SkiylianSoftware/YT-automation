from __future__ import annotations

import logging
import os
import re

from dotenv import load_dotenv
from pyyoutube import AccessToken, Channel, Client, Playlist, Video

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

PLAYLIST_REGEX = re.compile(r"(?P<series_name>[^\-]+)\- (?P<game_name>.*)")
VIDEO_REGEX = re.compile(
    r"(?P<game_name>[^:]+): (?P<series_name>[^#]+)#(?P<ep_number>\d+) \- (?P<title>.*)"
)


def get_client() -> Client:
    load_dotenv(".env.client")
    load_dotenv(".env.token")
    client = Client(
        client_id=os.getenv("client_id"),
        client_secret=os.getenv("client_secret"),
        access_token=os.getenv("access_token"),
        refresh_token=os.getenv("refresh_token"),
    )
    # refresh the token
    if client._has_auth_credentials():
        token: AccessToken = client.refresh_access_token(client.refresh_token)
        token.refresh_token = client.refresh_token
    # or generate new
    else:
        auth_url, _ = client.get_authorize_url()
        print(f"Visit {auth_url} to authorise the application.")
        auth_response = input("Insert the redirect URL after authenticating here:\n> ")
        token = client.generate_access_token(authorization_response=auth_response)

    # Save the token for next time
    with open(".env.token", "w") as f:
        f.write(
            "\n".join(
                [
                    f"access_token={token.access_token}",
                    f"refresh_token={token.refresh_token}",
                ]
            )
        )

    client.access_token = token.access_token
    client.refresh_token = token.refresh_token

    return client


def get_channel(client: Client) -> Channel:
    return client.channels.list(mine=True).items[0]


def get_videos_in_playlist(client: Client, playlist_id: str) -> list[Video]:
    videos: list[Video] = []
    for item in client.playlistItems.list(
        playlist_id=playlist_id, max_results=int(1e6)
    ).items:
        videos.extend(client.videos.list(video_id=item.contentDetails.videoId).items)
    return videos


def get_channel_videos(client: Client, channel: Channel) -> list[Video]:
    if upload_playlist := channel.contentDetails.relatedPlaylists.uploads:
        uploads = get_videos_in_playlist(client, playlist_id=upload_playlist)
        return [vid for vid in uploads if vid.status.privacyStatus == "public"]
    return []


def get_channel_playlists(client: Client, channel: Channel) -> list[Playlist]:
    found_playlists = client.playlists.list(channel_id=channel.id)
    return found_playlists.items


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
            game_name: str = search.group("game_name").strip()
            series_name: str = search.group("series_name").strip()
            shorthand = game_to_short(game_name)

            if shorthand not in mapping:
                mapping[shorthand] = {}

            mapping[shorthand][series_name] = playlist

    return mapping


def video_mapping(videos: list[Video]) -> dict[str, dict[str, list[Video]]]:
    """
    Returns: {GAME_ACRONYM: {Series_for_game: [videos_for_series, ...], ...}, ...}
    """
    mapping: dict[str, dict[str, list[Video]]] = {}
    for video in videos:
        if search := VIDEO_REGEX.search(video.snippet.title):
            game_name: str = search.group("game_name").strip()
            series_name: str = search.group("series_name").strip()
            shorthand = game_to_short(game_name)

            if shorthand not in mapping.keys():
                mapping[shorthand] = {}
            if series_name not in mapping[shorthand].keys():
                mapping[shorthand][series_name] = []

            mapping[shorthand][series_name].append(video)

    return mapping


def find_videos_not_in_playlists(
    client: Client,
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
                pl_vids = get_videos_in_playlist(client, pl.id)
                pl_ids = [pl_vid.id for pl_vid in pl_vids]
                for vid in vids:
                    if vid.id not in pl_ids:
                        missing.append((vid, pl))

    return missing


def add_video_to_playlists(
    client: Client, missing_vids: list[tuple[Video, Playlist]]
) -> None:
    for video, playlist in missing_vids:
        try:
            client.playlistItems.insert(
                parts="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist.id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video.id,
                        },
                    }
                },
            )
            logging.debug(
                f"Successfully added {video.snippet.title} to {playlist.snippet.title}!"
            )
        except Exception as e:
            logging.error(
                f"Failed to add {video.snippet.title} to {playlist.snippet.title}"
            )
            logging.error(e)


def main() -> int:
    client = get_client()
    logging.debug(f"Logged in with {client}")

    # Fetch channel
    channel = get_channel(client)
    logging.debug(f"Found channel: {channel.brandingSettings.channel.title}")

    # Fetch playlists
    channel_playlists = get_channel_playlists(client, channel)
    logging.debug(f"Found playlists: {channel_playlists}")

    # Create playlist mapping
    playlists = playlist_mapping(channel_playlists)
    logging.debug(f"Playlist mapping: {playlists}")

    # Fetch uploads
    channel_videos = get_channel_videos(client, channel)
    logging.debug(f"Found videos: {channel_videos}")

    # create video mapping
    videos = video_mapping(channel_videos)
    logging.debug(f"Video mapping: {videos}")

    # check all videos are in the correct playlists
    missing_from_playlists = find_videos_not_in_playlists(client, playlists, videos)

    # add video to playlist if missing
    if missing_from_playlists:
        add_video_to_playlists(client, missing_from_playlists)
    else:
        logging.info("No videos are missing from their respective playlists!")

    return 0


if __name__ == "__main__":
    quit(main())
