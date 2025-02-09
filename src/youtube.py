"""Wrapper script to interact with YouTube API using py-youtube."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from logging import Logger, getLogger
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from pyyoutube import AccessToken, Channel, Client, Playlist, Video


@dataclass
class YouTube:
    """Wrapper class around the YouTube API."""

    youtube_env: Path

    client: Client = None

    @property
    def logger(self) -> Logger:
        """Logger for the API."""
        return getLogger("youtube-api")

    def __write_creds__(self, token: AccessToken) -> None:
        """Store the credentials to the persistent location."""
        self.youtube_env.write_text(
            "\n".join(
                [
                    f"client_id={self.client.client_id}",
                    f"client_secret={self.client.client_secret}",
                    f"access_token={token.access_token}",
                    f"refresh_token={token.refresh_token}",
                ]
            )
        )
        self.logger.debug(f"Wrote access_token to {self.youtube_env}")

    def __oath_ctx__(self) -> AccessToken:
        """Generate OAuth credentials for first initialisation."""
        if not self.client:
            raise RuntimeError(
                "Cannot generate an OAuth redirect when client "
                "is uninitialised!\nRun YouTube.authenticate() instead."
            )
        self.logger.debug("Access token not found, requesting authorisation")
        auth_url, _ = self.client.get_authorize_url()
        print(f"Visit {auth_url} to authorise this application.")
        token = self.client.generate_access_token(
            authorization_response=input("Insert the redirect URL here:\n> ")
        )
        self.logger.debug("Auth complete")
        return token

    def authenticate(self) -> None:
        """Authenticate to the YouTube API."""
        if not self.youtube_env.exists():
            raise FileExistsError("YouTube environment file does not exist!")

        load_dotenv(str(self.youtube_env.resolve()))

        self.client = Client(
            client_id=getenv("client_id"),
            client_secret=getenv("client_secret"),
            access_token=getenv("access_token"),
            refresh_token=getenv("refresh_token"),
        )
        self.logger.debug(f"Authenticating with client {self.client.client_id}")

        token: AccessToken = (
            self.client.refresh_access_token(self.client.refresh_token)
            if self.client._has_auth_credentials()
            else self.__oath_ctx__()
        )
        token.refresh_token = token.refresh_token or self.client.refresh_token
        self.logger.debug(f"Loaded access token, expires in {token.expires_in}s")

        self.client.access_token = token.access_token
        self.client.refresh_token = token.refresh_token

        self.__write_creds__(token)

    # Generic actions

    def show(self, obj: list[Playlist | Video]) -> list[str]:
        """Convert list of playlists or videos to a list of their titles."""
        return [x.snippet.title for x in obj]

    # Channel operations

    @property
    def me(self) -> Channel:
        """Primary channel for the authenticated client."""
        return self.client.channels.list(mine=True).items[0]

    @property
    def channel_name(self) -> str:
        """Channel name for `me`."""
        return self.me.brandingSettings.channel.title

    @property
    def safe_channel_name(self) -> str:
        """Channel name `me` converted to underscores and lowercase."""
        return self.channel_name.lower().replace(" ", "_").replace("-", "_")

    def channel(self, channel_id: str) -> Channel:
        """Channel object for the channel `channel_id`."""
        return self.client.channels.list(channel_id=channel_id).items[0]

    def channel_playlists(self, channel_id: str) -> list[Playlist]:
        """List of all playlists for the channel `channel_id`."""
        return self.client.playlists.list(channel_id=channel_id).items

    def channel_videos(self, channel_id: str) -> list[Video]:
        """List of all videos for the channel `channel_id`."""
        if upload_playlist := self.channel(
            channel_id
        ).contentDetails.relatedPlaylists.uploads:
            return self.playlist_videos(playlist_id=upload_playlist)
        return []

    # Playlist operations

    @property
    def playlists(self) -> list[Playlist]:
        """List of all playlists for `me`."""
        return self.client.playlists.list(mine=True).items

    def playlist_videos(self, playlist_id: str) -> list[Video]:
        """List of all `videos` in the playlist with ID `playlist_id`."""
        videos: list[Video] = []
        for item in self.client.playlistItems.list(
            playlist_id=playlist_id, max_results=int(1e6)
        ).items:
            videos.extend(
                self.client.videos.list(video_id=item.contentDetails.videoId).items
            )
        return videos

    def add_to_playlist(self, playlist: Playlist, video: Video) -> None:
        """Add a `video` to the `playlist`."""
        self.client.playlistItems.insert(
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

    # Video operations

    @property
    def videos(self) -> list[Video]:
        """List of all uploaded videos for `me`."""
        return self.playlist_videos(self.me.contentDetails.relatedPlaylists.uploads)

    def videos_with_status(self, status: str = "public") -> list[Video]:
        """List of videos with a given status for `me`."""
        return [video for video in self.videos if video.status.privacyStatus == status]

    @property
    def public_videos(self) -> list[Video]:
        """List of public videos for `me`."""
        return self.videos_with_status("public")

    @property
    def private_videos(self) -> list[Video]:
        """List of private videos for `me`."""
        return self.videos_with_status("private")

    @property
    def unlisted_videos(self) -> list[Video]:
        """List of unlisted videos for `me`."""
        return self.videos_with_status("unlisted")

    @property
    def scheduled_videos(self) -> list[Video]:
        """List of scheduled videos for `me`."""
        return [
            video
            for video in self.videos
            if (sched := video.status.publishAt)
            and (datetime.fromisoformat(sched) > datetime.now(UTC))
        ]

    def video(self, video_id: str) -> Video:
        """Return video object from video ID."""
        return self.client.videos.list(video_id=video_id).items[0]
