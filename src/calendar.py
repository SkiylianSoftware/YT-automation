"""Wrapper script to interact with the Google Calendar API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from json import loads
from logging import Logger, getLogger
from pathlib import Path
from typing import Any, Optional, TypeVar

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

T = TypeVar("T")

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def clean_dict(D: dict[str, Any]) -> dict[str, Any]:
    """Return a dictionary object without `None` values."""
    return {k: v for k, v in D.items() if v is not None}


@dataclass
class CalendarAPI:
    """API Interaction and Authentication."""

    calendar_env: Path
    timezone: str

    service: build = None

    @property
    def refresh_env(self) -> Path:
        return self.calendar_env.with_suffix(f"{self.calendar_env.suffix}.refresh")

    @property
    def logger(self) -> Logger:
        """Logger object for CalendarAPI."""
        return getLogger("calendar-api")

    def __write_creds__(self, credentials: Credentials) -> None:
        """Write credentials to the persistent storage location."""
        self.refresh_env.write_text(credentials.to_json())
        self.logger.debug(f"Wrote credentials to {self.calendar_env}")

    def authenticate(self) -> None:
        """Authenticate to Google calendar."""
        if not self.calendar_env.exists():
            raise FileExistsError("Calendar environment file does not exist!")

        # We attempt to use the credentials file directly
        try:
            self.logger.debug("Attempting to load token from file")
            creds = Credentials.from_authorized_user_info(
                loads(self.refresh_env.read_text()), scopes=SCOPES
            )
        # Otherwise, this might be the first run, and should be the login file
        except ValueError:
            self.logger.warning(
                "Could not load as token, attempting to load as user credentials"
            )
            flow = InstalledAppFlow.from_client_secrets_file(
                self.calendar_env.resolve(), scopes=SCOPES
            )
            creds = flow.run_local_server(port=0, open_browser=False)
        except Exception as e:
            raise e

        self.logger.debug("Loaded credentials")

        if creds.token_state.name != "FRESH":
            self.logger.debug("creds expired, refreshing")
            creds.refresh(Request())

        elif not creds.valid:
            raise Exception("OAuth credentials invalid!")

        self.__write_creds__(creds)

        self.service = build("calendar", "v3", credentials=creds)

    # Calendar operations

    def fetch_calendars(self) -> list[Calendar]:
        """Fetch all calendars for a google account."""
        self.logger.debug("Returning all calendars")
        _calendars = []
        page_token = None
        while True:
            calendars = self.service.calendarList().list(pageToken=page_token).execute()

            for calendar in calendars.get("items", []):
                cal = Calendar.from_api(calendar)
                cal.api = self
                cal.time_zone = self.timezone
                _calendars.append(cal)

            page_token = calendars.get("nextPageToken")
            if not page_token:
                break
        return _calendars

    def fetch_calendar(self, name: str) -> Calendar | None:
        """Fetch a specific calendar with name=`name` for a google account."""
        self.logger.debug(f"Searching for calendar {name}")
        for calendar in self.fetch_calendars():
            if name in [calendar.summary, calendar.id]:
                self.logger.debug(f"Found calendar {calendar}")
                return calendar
        self.logger.debug("Calendar not found")
        return None

    def create_calendar(self, cal: dict[str, Any] | Calendar) -> Calendar:
        """Create a calendar on the google account."""
        calendar = clean_dict(cal if isinstance(cal, dict) else cal.to_dict())

        if existing := self.fetch_calendar(calendar["summary"]):
            return existing

        self.logger.debug(f"Creating new calendar {calendar}")
        created = self.service.calendars().insert(body=calendar).execute()
        self.logger.debug(f"Created new calendar {created}")

        cal = Calendar.from_api(created)
        cal.api = self
        cal.time_zone = self.timezone

        return cal

    # Events operations

    def __fetch_events__(self, calendar: Calendar) -> list[Event]:
        """Fetch all the events on a `calendar`."""
        self.logger.debug(f"Returning all events for {calendar}")
        _events: list[Event] = []
        page_token = None
        while True:
            params = {"calendarId": calendar.id, "pageToken": page_token}
            if token := calendar.synch_token:
                params["synchToken"] = token

            try:
                events = self.service.events().list(**params).execute()
                for event in events.get("items", []):
                    evt = Event.from_api(event)
                    self.logger.debug(f"found event: {evt}")
                    _events.append(evt)
                page_token = events.get("nextPageToken")
                calendar.synch_token = events.get("nextsynchToken")
                if not page_token:
                    break

            except HttpError as e:
                # expired synch token
                if e.resp.status == 410:
                    calendar.synch_token = None
                    self.logger.warning("synch token expired, fetching events again")
                    return self.__fetch_events__(calendar)
                raise e

        return _events

    def __delete_event__(self, calendar: Calendar, event: Event) -> None:
        """Delete a specific `event` from a `calendar`."""
        self.logger.debug(f"Deleting event {event} from calendar {calendar}")
        self.service.events().delete(calendarId=calendar.id, eventId=event.id).execute()

    def __synch_events__(self, calendar: Calendar) -> None:
        """Synch all events bidirectionally between local cache and remote API."""
        fetched_events = self.__fetch_events__(calendar)
        event_cache = calendar._events_cache_

        # push events from cache to api
        for i, event in enumerate(event_cache):
            for fetched in fetched_events:
                if fetched.id == event.id:
                    self.logger.debug(f"event {event} already in calendar, updating")
                    self.service.events().update(
                        calendarId=calendar.id, eventId=event.id, body=event.to_dict()
                    ).execute()
                    break
            else:
                self.logger.debug(f"event {event} new to calendar, creating")
                created_event = (
                    self.service.events()
                    .insert(calendarId=calendar.id, body=event.to_dict())
                    .execute()
                )
                calendar._events_cache_[i] = created_event

        # pull events from api to cache
        for event in fetched_events:
            for i, cached in enumerate(event_cache):
                if event.id == cached.id:
                    calendar._events_cache_[i] = event
                    break
            else:
                calendar._events_cache_.append(event)


@dataclass
class Event:
    """Representation of an Event in a google calendar."""

    summary: str = ""
    id: Optional[str] = None
    description: Optional[str] = None
    start: datetime = field(default_factory=lambda: datetime.now(UTC))
    end: datetime = field(default_factory=lambda: datetime.now(UTC))

    timezone: str = "UTC"

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary representiation."""
        return {
            "id": self.id,
            "summary": self.summary,
            "description": self.description,
            "start": {"dateTime": self.start.isoformat(), "timeZone": self.timezone},
            "end": {"dateTime": self.end.isoformat(), "timeZone": self.timezone},
        }

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Event:
        """Convert from a dictionary representation."""
        return cls(
            id=data.get("id"),
            summary=data.get("summary", ""),
            description=data.get("description"),
            start=datetime.fromisoformat(data["start"]["dateTime"]),
            end=datetime.fromisoformat(data["end"]["dateTime"]),
        )

    def __str__(self) -> str:
        """Event string representation."""
        return f"Event: {self.summary} at {self.start}"


@dataclass
class Calendar:
    """Object representing a Calendar in google calendar."""

    summary: str
    id: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    time_zone: str = "UTC"
    selected: bool = True
    access_role: str = "owner"
    hidden: bool = False

    api: Optional[CalendarAPI] = None
    synch_token: Optional[str] = None
    _events_cache_: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary representation."""
        return {
            "id": self.id,
            "summary": self.summary,
            "description": self.description,
            "location": self.location,
            "timeZone": self.time_zone,
            "selected": self.selected,
            "accessRole": self.access_role,
            "hidden": self.hidden,
        }

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Calendar:
        """Convert from a dictionary representaiton."""
        return cls(
            id=data.get("id"),
            summary=data.get("summary", ""),
            description=data.get("description"),
            location=data.get("location"),
            time_zone=data.get("timeZone", "UTC"),
            selected=data.get("selected", True),
            access_role=data.get("access_role", "owner"),
            hidden=data.get("hidden", False),
        )

    def __str__(self) -> str:
        """Calendar string representation."""
        return f"Calendar: {self.summary}"

    def ensure_events_(self, evts: list[Event] | list[dict[str, Any]]) -> list[Event]:
        """Convert a list of `Event` of `dict` into a list of `Event`."""
        return [evt if isinstance(evt, Event) else Event.from_api(evt) for evt in evts]

    @property
    def events(self) -> list[Event]:
        """Return all known events on this calendar.

        fetches from the cache if found, or remotely if not.
        """
        if self._events_cache_:
            return self.ensure_events_(self._events_cache_)
        if api := self.api:
            self._events_cache_ = api.__fetch_events__(self)
            return self.ensure_events_(self._events_cache_)
        raise RuntimeError("Cannot search for events on calendar without API object")

    def synch(self) -> None:
        """Synchhronise local state with the API state."""
        if api := self.api:
            api.__synch_events__(self)
        else:
            raise RuntimeError("Cannot synch to a calendar without API object")

    def update_event(self, old_event: Event, new_event: Event) -> None:
        """Update an `Event` object.

        `old_event` will contain the non-None details of `new_event` in the cache.
        run `synch` to push changes to the API.
        """
        for i, event in enumerate(self._events_cache_):
            if event.id == old_event.id:
                new_detail = clean_dict(old_event.to_dict()) | clean_dict(
                    new_event.to_dict()
                )
                self._events_cache_[i] = Event.from_api(new_detail)
                return
        if api := self.api:
            api.logger.warning(f"Could not find event {old_event} to update!")
        else:
            raise RuntimeError("Cannot update events on calendar without API object")

    def create_event(self, new_event: Event) -> None:
        """Add `new_event` to the events cache.

        run `synch` to push changes to the API.
        """
        self._events_cache_.append(new_event)

    def delete_event(self, event: Event) -> None:
        """Delete `event` from the events cache.

        run `synch` to push changes to the API.
        """
        if api := self.api:
            api.__delete_event__(self, event)
            self._events_cache_.remove(event)
        else:
            raise RuntimeError("Cannot delete events on calendar without API object")
