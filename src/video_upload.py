from .API.youtube import YouTube
from argparse import Namespace
from .API.database import Database

from logging import getLogger

LOG = getLogger("upload-video")

# Database 

def upload_video(args: Namespace, yt: YouTube) -> int:
    """Video upload GUI."""

    log=LOG.getChild("upload")

    print(args.db_path)

    print(yt.public_videos[-1])