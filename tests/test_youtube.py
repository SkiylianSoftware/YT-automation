# from argparse import Namespace
# from pathlib import Path
from unittest.mock import patch  # MagicMock

from src.main import main

# import pytest


# from src.youtube import YouTube


# TODO: Fix
# def test_authenticate_success():
#     # TODO: Add a youtube fixture so we're not stuck with this
#     yt = MagicMock()
#     yt.client = MagicMock()
#     yt.client._has_auth_credentials.return_value = True
#     yt.client.refresh_access_token.return_value = MagicMock(
#         access_token="new_token", refresh_token="new_refresh"
#     )

#     yt.authenticate()

#     assert yt.client.access_token == "new_token"
#     assert yt.client.refresh_token == "new_refresh"


# TODO: Fix
# def test_authenticate_failure():
#     # TODO: Add a youtube fixture so we're not stuck with this
#     yt = MagicMock()
#     yt.client = MagicMock()
#     yt.client._has_auth_credentials.return_value = False
#     yt.client.generate_access_token.side_effect = RuntimeError("Auth failed")

#     with pytest.raises(RuntimeError, match="Auth failed"):
#         yt.authenticate()

# TODO: Fix
# def test_videos_with_status():
#     # TODO: Add a youtube fixture so we're not stuck with this
#     yt = MagicMock()
#     yt.videos = [
#         MagicMock(status=MagicMock(privacyStatus="public")),
#         MagicMock(status=MagicMock(privacyStatus="private")),
#         MagicMock(status=MagicMock(privacyStatus="unlisted")),
#     ]

#     assert len(yt.videos_with_status("public")) == 1
#     assert len(yt.videos_with_status("private")) == 1
#     assert len(yt.videos_with_status("unlisted")) == 1


def test_main_no_args():
    with patch("sys.argv", ["main.py"]):
        assert main() == 0


# TODO: Fix
# def test_main_with_playlist_automation():
#     with patch("sys.argv", ["main.py", "playlist-automation"]), patch(
#         "src.playlist_automation"
#     ) as mock_func:
#         mock_func.return_value = 0
#         assert main() == 0
#         mock_func.assert_called_once()
