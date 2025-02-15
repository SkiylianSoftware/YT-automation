from argparse import Namespace
from logging import getLogger

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .calendar import SCOPES, CalendarAPI
from .youtube import YouTube

LOG = getLogger("re-auth")


def re_auth(args: Namespace, yt: YouTube) -> int:
    """Entrypoint for calendar automation."""
    log = LOG.getChild("calendar")

    # Authenticate to Google Calendar
    cal = CalendarAPI(calendar_env=args.env_calendar, timezone=args.timezone)
    try:
        cal.authenticate()
    except Exception as e:
        log.error("Could not authenticate to Google calendar")
        log.error(e)
        flow = InstalledAppFlow.from_client_secrets_file(
            cal.calendar_env.resolve(), scopes=SCOPES
        )
        creds = flow.run_local_server(port=0, open_browser=False)

        if creds.token_state.name != "FRESH":
            log.debug("creds expired, refreshing")
            creds.refresh(Request())

        elif not creds.valid:
            raise Exception("OAuth credentials invalid!")

        cal.__write_creds__(creds)
