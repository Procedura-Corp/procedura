# utils/types.py  (or keep near logger if you prefer)
from typing import TypedDict, Literal, Optional

class TextFrame(TypedDict):
    type: Literal["text"]
    content: str                # required

class PictureFrame(TypedDict):
    type: Literal["picture"]
    src: str                    # required
    caption: Optional[str]

StoryFrame = TextFrame | PictureFrame         # 👉 easy to extend later
