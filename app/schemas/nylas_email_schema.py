"""Pydantic models for Nylas email messages and the send-email request."""

from pydantic import BaseModel, ConfigDict, Field


class Sender(BaseModel):
    email: str
    # Real senders may have no display name; Nylas then omits "name".
    name: str = ""


class Attachment(BaseModel):
    content_disposition: str | None = None
    content_id: str | None = None
    content_type: str
    filename: str
    grant_id: str
    id: str
    is_inline: bool = False
    size: int


class EmailObject(BaseModel):
    # "from" is a Python keyword: accept both "from" and "from_" as input,
    # and serialize with by_alias=True so API output uses "from".
    model_config = ConfigDict(populate_by_name=True)

    attachments: list[Attachment] = []
    bcc: list = []
    body: str
    cc: list = []
    date: int  # unix timestamp
    folders: list = []
    from_: list[Sender] = Field(alias="from")
    grant_id: str
    id: str
    object: str
    reply_to: list = []
    snippet: str
    starred: bool
    subject: str
    thread_id: str
    to: list
    unread: bool


class EmailRequest(BaseModel):
    subject: str
    body: str
    to_email: str
