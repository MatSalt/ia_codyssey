"""Shared API contracts. Dates serialize as ISO strings; timestamps are UTC."""
from datetime import date
import re
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, StrictStr, field_validator


def iso_date(value):
    if type(value) is date:
        return value
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Expected a date in YYYY-MM-DD format')
    return date.fromisoformat(value)


ISODate = Annotated[date, BeforeValidator(iso_date)]
Count = Annotated[int, Field(strict=True, ge=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class RecordCreate(Contract):
    date: ISODate
    value: Count
    memo: StrictStr = ''


class RecordUpdate(Contract):
    value: Count
    memo: StrictStr


class Record(RecordCreate):
    id: StrictStr


class MessageInput(Contract):
    role: Literal['user', 'assistant']
    content: StrictStr


class Message(MessageInput):
    created_at: AwareDatetime

    @field_validator('created_at')
    @classmethod
    def utc_time(cls, value):
        from datetime import timezone
        return value.astimezone(timezone.utc)


class ConversationCreate(Contract):
    title: StrictStr
    messages: list[MessageInput]


class ConversationListItem(Contract):
    id: StrictStr
    title: StrictStr
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator('created_at', 'updated_at')
    @classmethod
    def utc_time(cls, value):
        from datetime import timezone
        return value.astimezone(timezone.utc)


class Conversation(ConversationListItem):
    messages: list[Message]


class Period(Contract):
    start: ISODate
    end: ISODate


class Extreme(Contract):
    value: Count
    dates: list[ISODate]


class Metrics(Contract):
    total: Count
    daily_average: float | None
    max: Extreme | None
    min: Extreme | None


class ComparisonPeriod(Period):
    average: float


class Comparison(Contract):
    status: Literal['insufficient_data', 'zero_baseline', 'comparable']
    window_days: Count
    previous: ComparisonPeriod | None
    recent: ComparisonPeriod | None
    change_percent: float | None
    trend: Literal['increase', 'decrease', 'unchanged', 'insufficient_data']
    message: StrictStr


class Summary(Contract):
    period: Period | None
    count: Count
    calendar_days: Count
    filled_zero_days: Count
    metrics: Metrics
    comparison: Comparison
    notable_memos: list[RecordCreate]


class ChatRequest(Contract):
    message: Annotated[str, Field(strict=True, min_length=1, max_length=4000)]
    conversation_id: Annotated[str, Field(strict=True, min_length=1)] | None = None

    @field_validator('message')
    @classmethod
    def nonblank_message(cls, value):
        if not value.strip():
            raise ValueError('Message cannot be blank')
        return value


class ChatResponse(Contract):
    conversation_id: StrictStr
    answer: StrictStr
