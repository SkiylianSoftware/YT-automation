from argparse import Namespace
from logging import getLogger

from .calendar import CalendarAPI, Event, Calendar
from .youtube import Video, YouTube
from isodate import parse_duration, parse_datetime
import re

LOG = getLogger("calendar-automation")

EVT_VID_ID = re.compile(r"ID: (?P<video_id>\S+)")

def fetch_video_event(video: Video, events: list[Event]) -> Event | None:
    for event in events:
        if search := EVT_VID_ID.search(event.description):
            if search.group(1) == video.id:
                return event
    return None

def add_videos_to_calendar(videos: list[Video], calendar: Calendar) -> None:
    """Add videos to calendar, or update the calendar event details if different"""
    log = LOG.getChild("calendar-synch")

    events = calendar.events

    for video in videos:
        if video.status.privacyStatus == "public":
            video_publish = parse_datetime(video.snippet.publishedAt)
        else:
            video_publish = parse_datetime(video.status.publishAt)
        video_duration = parse_duration(video.contentDetails.duration)

        video_event = Event(
            summary=video.snippet.title,
            description=f"ID: {video.id}\nDescription: {video.snippet.description}",
            start=video_publish,
            end=video_publish+video_duration
        )

        if found_event := fetch_video_event(video, events=events):
            log.debug(f"video {video.snippet.title} already in calendar {found_event.summary}, updating")
            calendar.update_event(found_event, video_event)

        else:
            log.debug(f"video {video.snippet.title} not in calendar, creating")
            calendar.create_event(video_event)

        
    
    log.debug(f"All {len(videos)} added to calendar {calendar.summary}, synching")
    calendar.synch()

def remove_videos_from_calendar(videos: list[Video], calendar: Calendar)-> None:
    """Remove videos from a calendar if they exist"""

    log = LOG.getChild("calendar-delete")
    events = calendar.events
    deleted_count = 0

    for video in videos:
        if found_event := fetch_video_event(video, events):
            log.debug(f"Video {video.snippet.title} in calendar {calendar.summary} when it should be deleted")
            deleted_count += 1
            calendar.delete_event(found_event)

    if deleted_count:
        log.info(f"{deleted_count} Videos were removed from {calendar.summary}")
    else:
        log.info(f"No videos removed from {calendar.summary}")

def purge_nonexistent_videos(videos: list[Video], calendar: Calendar) -> None:
    """Remove video events for videos that no longer exist."""

    log = LOG.getChild("calendar-purge")
    events = calendar.events
    deleted_count = 0

    for event in events:
        if search := EVT_VID_ID.search(event.description):
            video_id = search.group("video_id").strip()
            
            for video in videos:
                if video_id == video.id:
                    break
            else:
                deleted_count += 1
                log.debug(f"Video {video_id} in {calendar.summary} no longer exists")
                calendar.delete_event(event)

    if deleted_count:
        log.info(f"{deleted_count} non-existent videos were removed from {calendar.summary}")
    else:
        log.info(f"No videos removed from {calendar.summary}")


def calendar_automation(args: Namespace, yt: YouTube) -> int:

    # Authenticate to Google Calendar
    try:
        cal = CalendarAPI(calendar_env=args.env_calendar, timezone=args.timezone)
        cal.authenticate()
    except Exception as e:
        LOG.error("Could not authenticate to Google calendar")
        LOG.error(e)
        return 1

    # Check the calendars exist

    publicCalendar = cal.create_calendar(
        Calendar(
            summary="Videos (Public)",
            description=f"Publically released videos for {yt.channel_name}",
            # colour=CalendarColour.tomato,
        )
    )
    privateCalendar = cal.create_calendar(
        Calendar(
            summary="Videos (Private)",
            description=f"Unreleased videos for {yt.channel_name}",
            # colour=CalendarColour.lavendar,
        )
    )
    LOG.debug(
        f"Fetched or created the public ({publicCalendar}) and private ({privateCalendar}) calendars."
    )

    # Fetch all the public videos and add to the public calendar

    public_videos = yt.public_videos
    LOG.debug(f"Found {len(public_videos)} public videos: {public_videos}")

    if public_videos:
        add_videos_to_calendar(public_videos, publicCalendar)

    # Fetch all the private videos and add to the private calendar
    scheduled_videos = yt.scheduled_videos
    LOG.debug(f"found {len(scheduled_videos)} scheduled videos")
    

    if scheduled_videos:
        add_videos_to_calendar(scheduled_videos, privateCalendar)

    # Remove public videos from the private calendar
    remove_videos_from_calendar(scheduled_videos, publicCalendar)

    # Remove videos that don't exist
    purge_nonexistent_videos(yt.videos, privateCalendar)
    purge_nonexistent_videos(yt.videos, publicCalendar)

    LOG.info("All videos synched to calendars")

    return 0
