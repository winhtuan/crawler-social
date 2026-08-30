from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    id: str
    name: str
    profileUrl: str
    profilePic: str


class PhotoImage(BaseModel):
    uri: str
    height: Optional[int] = None
    width: Optional[int] = None


class MediaFeedback(BaseModel):
    can_viewer_comment: bool = False
    id: Optional[str] = None


class Media(BaseModel):
    model_config = ConfigDict(extra="allow")
    thumbnail: Optional[str] = None
    __typename: Optional[str] = None
    __isMedia: Optional[str] = None
    accent_color: Optional[str] = None
    photo_product_tags: list = Field(default_factory=list)
    photo_image: Optional[PhotoImage] = None
    url: Optional[str] = None
    id: Optional[str] = None
    feedback: Optional[MediaFeedback] = None
    ocrText: Optional[str] = None


class Post(BaseModel):
    facebookUrl: Optional[str] = None
    postId: Optional[str] = None
    pageName: Optional[str] = None
    url: Optional[str] = None
    time: Optional[str] = None
    timestamp: Optional[int] = None
    user: Optional[User] = None
    text: Optional[str] = None
    likes: int = 0
    comments: int = 0
    commentsData: list = Field(default_factory=list)
    shares: int = 0
    topReactionsCount: int = 0
    media: list[Media] = Field(default_factory=list)
    feedbackId: Optional[str] = None
    reactionHahaCount: int = 0
    reactionLikeCount: int = 0
    reactionSadCount: int = 0
    reactionLoveCount: int = 0
    paidPartnership: bool = False
    topLevelUrl: Optional[str] = None
    facebookId: Optional[str] = None
    inputUrl: Optional[str] = None
