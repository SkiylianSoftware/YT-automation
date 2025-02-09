from sqlalchemy.orm import declarative_base

from sqlalchemy import Column, Integer, String, Date, ForeignKey, Enum, Table
from sqlalchemy.orm import relationship
from pyyoutube import Video as YTVideo

Base = declarative_base()

import enum

video_playlist_relation = Table(
    "video_playlist_relation", Base.metadata,
    Column("video_id", Integer, ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True),
    Column("playlist_id", Integer, ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True)
)

class VideoStatus(enum.Enum):
    public="public"
    unlisted="unlisted"
    private="private"

class Video(Base):
    __tablename__ = "videos"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    tags=Column(String, nullable=True)
    thumbnail=Column(String, nullable=False)
    status=Column(Enum(VideoStatus), nullable=False)
    publish_date = Column(Date, nullable=True)

    playlists = relationship("Playlist", secondary=video_playlist_relation, back_populates="video")

    @classmethod
    def to_video_obj(cls) -> YTVideo:
        return YTVideo()

class Playlist(Base):
    __tablename__ = "playlists"

    id=Column(String, primary_key=True)
    name=Column(String, nullable=False)
    video_id=Column(Integer, ForeignKey("videos.id"), nullable=False)

    video = relationship("Video", secondary=video_playlist_relation, back_populates="playlists")