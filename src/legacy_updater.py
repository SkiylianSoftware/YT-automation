"""Bulk update legacy YouTube video and playlist titles."""

from __future__ import annotations

from argparse import Namespace
from logging import getLogger

from .playlist_automation import OLD_PLAYLIST_REGEX, OLD_VIDEO_REGEX
from .youtube import YouTube

LOG = getLogger("legacy-updater")


def legacy_update(args: Namespace, yt: YouTube) -> int:
    """Entrypoint for bulk updating legacy titles."""
    log = LOG.getChild("execution")
    dry_run = not args.commit

    if dry_run:
        log.info("Executing DRY RUN. Pass --commit to apply changes to YouTube.")
    else:
        log.warning("Executing LIVE RUN. Changes will be pushed to YouTube API.")

    # Trackers for the summary
    playlists_updated = 0
    videos_updated = 0

    # --- PROCESS PLAYLISTS ---
    log.info("--- PLAYLIST TITLE UPDATES ---")
    channel_playlists = yt.playlists
    for playlist in channel_playlists:
        old_title = playlist.snippet.title
        if search := OLD_PLAYLIST_REGEX.search(old_title):
            series = str(search.group("series") or "").strip()
            category = str(search.group("category") or "").strip()
            
            # Format: Series | Category
            new_title = f"{series} | {category}" if series else category
            
            if new_title != old_title:
                log.info(f"Rename: '{old_title}'  =>  '{new_title}'")
                playlists_updated += 1
                
                if not dry_run:
                    try:
                        # Extract the full snippet to avoid wiping existing metadata
                        playlist_snippet = playlist.snippet.to_dict()
                        playlist_snippet["title"] = new_title
                        
                        yt.client.playlists.update(
                            parts="snippet",
                            body={
                                "id": playlist.id,
                                "snippet": playlist_snippet
                            }
                        )
                    except Exception as e:
                        log.error(f"Failed to update playlist '{old_title}': {e}")

    # --- PROCESS VIDEOS ---
    log.info("--- VIDEO TITLE UPDATES ---")
    channel_videos = yt.public_videos
    for video in channel_videos:
        old_title = video.snippet.title
        if search := OLD_VIDEO_REGEX.search(old_title):
            title = str(search.group("title") or "").strip()
            ep = str(search.group("ep_number") or "").strip()
            series = str(search.group("series") or "").strip()
            category = str(search.group("category") or "").strip()
            
            # Format: Title | Series #Ep | Category
            if series:
                new_title = f"{title} | {series} #{ep} | {category}"
            else:
                new_title = f"{title} | {category} #{ep}"
                
            if new_title != old_title:
                log.info(f"Rename: '{old_title}'  =>  '{new_title}'")
                videos_updated += 1
                
                if not dry_run:
                    try:
                        # Extract the full snippet to preserve descriptions and tags
                        video_snippet = video.snippet.to_dict()
                        video_snippet["title"] = new_title
                        
                        yt.client.videos.update(
                            parts="snippet",
                            body={
                                "id": video.id,
                                "snippet": video_snippet
                            }
                        )
                    except Exception as e:
                        log.error(f"Failed to update video '{old_title}': {e}")

    # --- SUMMARY ---
    log.info("--- SUMMARY ---")
    log.info(f"Playlists to update: {playlists_updated}")
    log.info(f"Videos to update: {videos_updated}")
    
    if dry_run:
        log.info("Dry run complete. No changes were made.")
    else:
        log.info("Live run complete. Changes successfully pushed to YouTube.")

    return 0