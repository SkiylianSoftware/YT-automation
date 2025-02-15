from argparse import Namespace
from logging import getLogger

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

from .calendar import SCOPES, CalendarAPI
from .youtube import YouTube

LOG = getLogger("re-auth")


def re_auth(args: Namespace, yt: YouTube) -> int:
    """Entrypoint for re-authentication."""
    # Authenticate to Google Calendar
    log = LOG.getChild("calendar")
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
            log.error("OAuth credentials invalid!")
            return 1

        cal.__write_creds__(creds)

    # Authenticate to the next thing

    return 0
