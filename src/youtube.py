"""Wrapper script to interact with YouTube API using py-youtube."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from logging import Logger, getLogger
from os import getenv
from pathlib import Path
from typing import Callable, TypeVar

from dotenv import load_dotenv
from pyyoutube import AccessToken, Caption, Channel, Client, Playlist, Video
from pyyoutube.error import PyYouTubeException

T = TypeVar("T")

# Short-term / transient failures that are worth retrying with backoff.
RETRIABLE_REASONS = {
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "backendError",
    "internalError",
    "SERVICE_UNAVAILABLE",
}
# Daily quota exhaustion; retrying within the same day is pointless.
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}


class QuotaExceededError(RuntimeError):
    """Raised when the daily YouTube API quota has been exhausted."""


@dataclass
class YouTube:
    """Wrapper class around the YouTube API."""

    youtube_env: Path

    client: Client = None

    # force-ssl is required to list/delete caption tracks; the other two match
    # pyyoutube's defaults for video/profile access.
    scopes = (
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/userinfo.profile",
    )

    @property
    def logger(self) -> Logger:
        """Logger for the API."""
        return getLogger("youtube-api")

    @staticmethod
    def __error_reason__(exc: PyYouTubeException) -> str:
        """Extract the machine-readable error reason from an API exception."""
        response = getattr(exc, "response", None)
        if response is None:
            return ""
        try:
            errors = response.json().get("error", {}).get("errors", [])
        except Exception:
            return ""
        return errors[0].get("reason", "") if errors else ""

    def __call_api__(
        self,
        func: Callable[..., T],
        *args: object,
        retries: int = 5,
        base_delay: float = 2.0,
        **kwargs: object,
    ) -> T:
        """Call an API function, retrying transient errors with backoff.

        Daily quota exhaustion raises QuotaExceededError immediately, since it
        cannot recover until the quota resets.
        """
        for attempt in range(1, retries + 1):
            try:
                return func(*args, **kwargs)
            except PyYouTubeException as e:
                reason = self.__error_reason__(e)
                if reason in QUOTA_REASONS:
                    raise QuotaExceededError(
                        "Daily YouTube API quota exhausted. It resets at "
                        "midnight US Pacific; re-run afterwards. Already "
                        "cleaned videos are skipped automatically."
                    ) from e

                retriable = reason in RETRIABLE_REASONS or e.status_code in {
                    429,
                    500,
                    503,
                }
                if not retriable or attempt == retries:
                    raise

                delay = base_delay * 2 ** (attempt - 1) + random.uniform(0, 1)
                self.logger.warning(
                    f"Transient API error '{reason or e.status_code}'; "
                    f"retry {attempt}/{retries - 1} in {delay:.1f}s"
                )
                time.sleep(delay)
        # Unreachable, but satisfies the type checker.
        raise RuntimeError("Retry loop exited unexpectedly")

    def __raw_request__(
        self,
        path: str,
        method: str = "GET",
        params: dict | None = None,
        json: dict | None = None,
    ) -> dict:
        """Issue a raw API request and parse it (raises on API errors)."""
        response = self.client.request(
            method=method, path=path, params=params, json=json
        )
        return self.client.parse_response(response)

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
        print(
            "\nYouTube authorisation required:\n"
            "  1. Open this URL in a chromium browser and approve access:\n"
            f"     {auth_url}\n"
            "  2. Your browser will then land on a 'localhost refused to connect'\n"
            "     page. This is EXPECTED; nothing is served on localhost.\n"
            "  3. Copy the FULL URL from the browser's address bar (it contains\n"
            "     '?code=...') and paste it below.\n"
        )
        token = self.client.generate_access_token(
            authorization_response=input("Paste the redirect URL here:\n> ")
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
        # Ensure caption scopes are requested when (re)authorising.
        self.client.DEFAULT_SCOPE = list(self.scopes)
        self.logger.debug(f"Authenticating with client {self.client.client_id}")

        try:
            token: AccessToken = self.client.refresh_access_token(
                self.client.refresh_token
            )
        except Exception as e:
            self.logger.exception(e)
            token = self.__oath_ctx__()
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
        return self.__call_api__(self.client.channels.list, mine=True).items[0]

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
        return self.__call_api__(self.client.playlists.list, mine=True).items

    def playlist_videos(self, playlist_id: str) -> list[Video]:
        """List of all `videos` in the playlist with ID `playlist_id`."""
        # playlistItems.list is capped at 50 per page, so follow nextPageToken.
        video_ids: list[str] = []
        page_token: str | None = None
        while True:
            page = self.__call_api__(
                self.client.playlistItems.list,
                playlist_id=playlist_id,
                parts="contentDetails",
                max_results=50,
                page_token=page_token,
            )
            video_ids.extend(item.contentDetails.videoId for item in page.items)
            page_token = page.nextPageToken
            if not page_token:
                break

        # videos.list accepts up to 50 IDs per call.
        videos: list[Video] = []
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start : start + 50]
            videos.extend(
                self.__call_api__(self.client.videos.list, video_id=batch).items
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

    # Translation operations

    def video_localizations(self, video_id: str) -> dict[str, dict[str, str]]:
        """Return the localizations (translated titles/descriptions) for a video."""
        # pyyoutube's part allow-list omits "localizations", so bypass the
        # resource wrapper and hit the endpoint directly.
        data = self.__call_api__(
            self.__raw_request__,
            path="videos",
            params={"part": "localizations", "id": video_id},
        )
        items = data.get("items") or []
        if not items:
            return {}
        return items[0].get("localizations") or {}

    def set_video_localizations(
        self, video: Video, localizations: dict[str, dict[str, str]]
    ) -> None:
        """Replace a video's localizations, preserving its canonical snippet."""
        snippet = video.snippet
        body: dict = {
            "id": video.id,
            "snippet": {
                "title": snippet.title,
                "categoryId": snippet.categoryId,
                "description": snippet.description,
            },
            "localizations": localizations,
        }
        # Only send optional snippet fields when present to avoid clobbering them.
        if snippet.tags:
            body["snippet"]["tags"] = snippet.tags
        # The API rejects a non-empty localizations block without a
        # defaultLanguage, so fall back to a kept language when it is missing.
        default_language = snippet.defaultLanguage
        if not default_language and localizations:
            default_language = sorted(localizations)[0]
        if default_language:
            body["snippet"]["defaultLanguage"] = default_language
        # "localizations" is a valid API part but rejected by pyyoutube's
        # allow-list, so issue the update request directly.
        self.__call_api__(
            self.__raw_request__,
            method="PUT",
            path="videos",
            params={"part": "snippet,localizations"},
            json=body,
        )

    def video_captions(self, video_id: str) -> list[Caption]:
        """Return the caption tracks associated with a video."""
        return (
            self.__call_api__(
                self.client.captions.list, video_id=video_id, parts="snippet"
            ).items
            or []
        )

    def delete_caption(self, caption_id: str) -> None:
        """Delete a caption track by ID."""
        self.__call_api__(self.client.captions.delete, caption_id=caption_id)
