import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.calendar import CalendarAPI


@pytest.fixture
def mock_credentials(tmp_path: Path):
    creds_path = tmp_path / "calendar_token.json"
    creds_path.write_text(
        json.dumps(
            {
                "installed": {
                    "token": "test_token",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": "test",
                }
            }
        )
    )
    return creds_path


@pytest.fixture
def calendar_api(mock_credentials: Path):
    api = CalendarAPI(calendar_env=mock_credentials, timezone="UTC")
    api.service = MagicMock()
    return api


# TODO: This, but without the auth url reaching
# @patch("google.oauth2.credentials.Credentials.from_authorized_user_file")
# def test_authenticate(mock_creds, calendar_api: CalendarAPI):
#     mock_creds_instance = MagicMock(valid=True)
#     mock_creds_instance.to_json.return_value = str({"token": "fake_token"})
#     mock_creds.return_value = mock_creds_instance

#     calendar_api.authenticate()


# @patch("googleapiclient.discovery.build")
# def test_authenticate_refresh(mock_build, calendar_api: CalendarAPI):
#     mock_creds = MagicMock()
#     mock_creds.valid = False
#     mock_creds.token_state.name = "EXPIRED"
#     mock_creds.refresh = MagicMock()
#     mock_creds.to_json.return_value = str({"token": "fake_refreshed_token"})

#     with patch(
#         "google.oauth2.credentials.Credentials.from_authorized_user_file",
#         return_value=mock_creds,
#     ):
#         calendar_api.authenticate()


@patch("googleapiclient.discovery.build")
def test_fetch_calendars(mock_build, calendar_api: CalendarAPI):
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    mock_calendar_list = mock_service.calendarList.return_value
    mock_calendar_list.list.return_value.execute.return_value = {
        "items": [
            {"id": "calendar1", "summary": "Test Calendar 1"},
            {"id": "calendar2", "summary": "Test Calendar 2"},
        ]
    }

    calendar_api.service = mock_service
    calendars = calendar_api.fetch_calendars()

    assert len(calendars) == 2
    assert calendars[0].id == "calendar1"
    assert calendars[1].summary == "Test Calendar 2"
