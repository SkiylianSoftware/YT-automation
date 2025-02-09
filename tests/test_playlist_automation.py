from unittest.mock import MagicMock
from uuid import uuid4

from src.playlist_automation import (
    game_to_short,
    playlist_automation,
    playlist_mapping,
    video_mapping,
)


class MockResource:
    def __init__(self, title: str):
        self.snippet = type("Snippet", (), {"title": title})

    @property
    def id(self) -> str:
        return str(uuid4())


class MockPlaylist(MockResource):
    pass


class MockVideo(MockResource):
    pass


def test_game_to_short():
    assert game_to_short("kerbal space program") == "KSP"
    assert game_to_short("Kerbal Space Program") == "KSP"
    assert game_to_short("KSP") == "KSP"


def test_playlist_mapping():
    playlists = [
        MockPlaylist("Career - kerbal space program"),
        MockPlaylist("Sandbox - Kerbal Space Program"),
        MockPlaylist("Science - KSP"),
    ]
    result = playlist_mapping(playlists)
    assert result["KSP"]["Career"]
    assert result["KSP"]["Sandbox"]
    assert result["KSP"]["Science"]


def test_video_mapping():
    videos = [
        MockVideo("kerbal space program: Career #1 - Building"),
        MockVideo("Kerbal Space Program: Sandbox #2 - Launch"),
        MockVideo("KSP: Science #3 - Testing"),
    ]
    result = video_mapping(videos)
    assert result["KSP"]["Career"]
    assert result["KSP"]["Sandbox"]
    assert result["KSP"]["Science"]


def test_playlist_automation_fails(mocker):
    args = MagicMock()
    yt_mock = MagicMock()
    yt_mock.playlists = []
    yt_mock.public_videos = []

    result = playlist_automation(args, yt_mock)
    # Program fails if nothing is to be moved
    assert result == 1


def test_playlist_automation_succeeds(mocker):
    args = MagicMock()
    yt_mock = MagicMock()
    yt_mock.playlists = [MockPlaylist("KSP - Test")]
    yt_mock.public_videos = [MockVideo("KSP: Test #1 - title")]
    yt_mock.playlist_videos.return_value = []

    result = playlist_automation(args, yt_mock)
    # program succeeds we hope
    assert result == 0
