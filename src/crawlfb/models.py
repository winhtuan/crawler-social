from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class Attachment(BaseModel):
    model_config = ConfigDict(extra="allow")
    thumbnail: Optional[str] = None
    url: Optional[str] = None
    type: Optional[str] = None  # "Photo" | "Video"
    id: Optional[str] = None
    ocr_text: Optional[str] = None


class TopComment(BaseModel):
    text: str = ""
    author: str = ""
    likes: int = 0


class Comment(BaseModel):
    model_config = ConfigDict(extra="allow")
    comment_id: str = ""
    text: str = ""
    author: str = ""
    likes: int = 0
    date: str = ""
    threading_depth: int = 0
    comment_url: str = ""


class Post(BaseModel):
    facebook_url: Optional[str] = None
    text: Optional[str] = None
    author: Optional[str] = None
    page_name: Optional[str] = None
    timestamp: Optional[str] = None
    likes: int = 0
    comments: int = 0
    shares: int = 0
    reactions: dict[str, int] = Field(default_factory=dict)
    top_reactions_count: int = 0
    top_comments: list[TopComment] = Field(default_factory=list)
    comments_list: list[Comment] = Field(default_factory=list)
    is_video: bool = False
    views: int = 0
    hashtags: list[str] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    post_id: Optional[str] = None
