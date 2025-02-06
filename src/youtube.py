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
    youtube_env: Path

    client: Client = None

    @property
    def logger(self) -> Logger:
        return getLogger("youtube-api")

    def _write_creds_(self, token: AccessToken) -> None:
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

    def _oath_ctx(self) -> AccessToken:
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
            else self._oath_ctx()
        )
        token.refresh_token = token.refresh_token or self.client.refresh_token
        self.logger.debug(f"Loaded access token, expires in {token.expires_in}s")

        self.client.access_token = token.access_token
        self.client.refresh_token = token.refresh_token

        self._write_creds_(token)

    # Generic actions

    def show(self, obj: list[Playlist | Video]) -> list[str]:
        return [x.snippet.title for x in obj]

    # Channel operations

    @property
    def me(self) -> Channel:
        return self.client.channels.list(mine=True).items[0]

    @property
    def channel_name(self) -> str:
        return self.me.brandingSettings.channel.title

    @property
    def safe_channel_name(self) -> str:
        return self.channel_name.lower().replace(" ", "_").replace("-", "_")

    def channel(self, channel_id: str) -> Channel:
        return self.client.channels.list(channel_id=channel_id).items[0]

    def channel_playlists(self, channel_id: str) -> list[Playlist]:
        return self.client.playlists.list(channel_id=channel_id).items

    def channel_videos(self, channel_id: str) -> list[Video]:
        if upload_playlist := self.channel(
            channel_id
        ).contentDetails.relatedPlaylists.uploads:
            return self.playlist_videos(playlist_id=upload_playlist)
        return []

    # Playlist operations

    @property
    def playlists(self) -> list[Playlist]:
        return self.client.playlists.list(mine=True).items

    def playlist_videos(self, playlist_id: str) -> list[Video]:
        videos: list[Video] = []
        for item in self.client.playlistItems.list(
            playlist_id=playlist_id, max_results=int(1e6)
        ).items:
            videos.extend(
                self.client.videos.list(video_id=item.contentDetails.videoId).items
            )
        return videos

    def add_to_playlist(self, playlist: Playlist, video: Video) -> None:
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
        return self.playlist_videos(self.me.contentDetails.relatedPlaylists.uploads)

    def videos_with_status(self, status: str = "public") -> list[Video]:
        return [video for video in self.videos if video.status.privacyStatus == status]

    @property
    def public_videos(self) -> list[Video]:
        return self.videos_with_status("public")

    @property
    def private_videos(self) -> list[Video]:
        return self.videos_with_status("private")

    @property
    def unlisted_videos(self) -> list[Video]:
        return self.videos_with_status("unlisted")

    @property
    def scheduled_videos(self) -> list[Video]:
        return [
            video
            for video in self.videos
            if (sched := video.status.publishAt)
            and (datetime.fromisoformat(sched) > datetime.now(UTC))
        ]

    def video(self, video_id: str) -> Video:
        return self.client.videos.list(video_id=video_id).items[0]
