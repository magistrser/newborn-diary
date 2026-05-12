import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from domain.event import (
    BathPayload,
    BottleContents,
    BreastSide,
    CryingPayload,
    CryingReason,
    DiaperKind,
    DiaperPayload,
    DoctorVisitPayload,
    DoctorVisitType,
    EventType,
    FatherCalmingPayload,
    FeedBottlePayload,
    FeedBreastPayload,
    GasPayload,
    MedicationPayload,
    NotePayload,
    PumpPayload,
    SleepEndPayload,
    SleepStartPayload,
    SpitUpPayload,
    SpitUpVolume,
    TemperatureMethod,
    TemperaturePayload,
    TummyTimePayload,
    VaccinationPayload,
    WalkPayload,
    WeightPayload,
)


class _EventCreateBase(BaseModel):
    occurred_at: datetime
    raw_text: str | None = None
    source_type: str = 'api'
    source_message_id: str | None = None
    source_chat_id: int | None = None


# ── Sleep ─────────────────────────────────────────────────────────────────────

class SleepStartCreate(_EventCreateBase):
    type: Literal[EventType.sleep_start] = EventType.sleep_start
    payload: SleepStartPayload = Field(default_factory=SleepStartPayload)


class SleepEndCreate(_EventCreateBase):
    type: Literal[EventType.sleep_end] = EventType.sleep_end
    payload: SleepEndPayload


# ── Feeding ───────────────────────────────────────────────────────────────────

class FeedBreastCreate(_EventCreateBase):
    type: Literal[EventType.feed_breast] = EventType.feed_breast
    payload: FeedBreastPayload


class FeedBottleCreate(_EventCreateBase):
    type: Literal[EventType.feed_bottle] = EventType.feed_bottle
    payload: FeedBottlePayload = Field(default_factory=FeedBottlePayload)


class PumpCreate(_EventCreateBase):
    type: Literal[EventType.pump] = EventType.pump
    payload: PumpPayload = Field(default_factory=PumpPayload)


# ── Diaper ────────────────────────────────────────────────────────────────────

class DiaperCreate(_EventCreateBase):
    type: Literal[EventType.diaper] = EventType.diaper
    payload: DiaperPayload = Field(default_factory=DiaperPayload)


# ── Health & measurements ─────────────────────────────────────────────────────

class WeightCreate(_EventCreateBase):
    type: Literal[EventType.weight] = EventType.weight
    payload: WeightPayload


class TemperatureCreate(_EventCreateBase):
    type: Literal[EventType.temperature] = EventType.temperature
    payload: TemperaturePayload


class MedicationCreate(_EventCreateBase):
    type: Literal[EventType.medication] = EventType.medication
    payload: MedicationPayload


class VaccinationCreate(_EventCreateBase):
    type: Literal[EventType.vaccination] = EventType.vaccination
    payload: VaccinationPayload


class DoctorVisitCreate(_EventCreateBase):
    type: Literal[EventType.doctor_visit] = EventType.doctor_visit
    payload: DoctorVisitPayload = Field(default_factory=DoctorVisitPayload)


# ── Baby activities ───────────────────────────────────────────────────────────

class BathCreate(_EventCreateBase):
    type: Literal[EventType.bath] = EventType.bath
    payload: BathPayload = Field(default_factory=BathPayload)


class TummyTimeCreate(_EventCreateBase):
    type: Literal[EventType.tummy_time] = EventType.tummy_time
    payload: TummyTimePayload = Field(default_factory=TummyTimePayload)


class WalkCreate(_EventCreateBase):
    type: Literal[EventType.walk] = EventType.walk
    payload: WalkPayload = Field(default_factory=WalkPayload)


# ── Symptoms ──────────────────────────────────────────────────────────────────

class SpitUpCreate(_EventCreateBase):
    type: Literal[EventType.spit_up] = EventType.spit_up
    payload: SpitUpPayload = Field(default_factory=SpitUpPayload)


class CryingCreate(_EventCreateBase):
    type: Literal[EventType.crying] = EventType.crying
    payload: CryingPayload = Field(default_factory=CryingPayload)


class GasCreate(_EventCreateBase):
    type: Literal[EventType.gas] = EventType.gas
    payload: GasPayload = Field(default_factory=GasPayload)


# ── Other ─────────────────────────────────────────────────────────────────────

class FatherCalmingCreate(_EventCreateBase):
    type: Literal[EventType.father_calming] = EventType.father_calming
    payload: FatherCalmingPayload = Field(default_factory=FatherCalmingPayload)


class NoteCreate(_EventCreateBase):
    type: Literal[EventType.note] = EventType.note
    payload: NotePayload


# ── Discriminated union ───────────────────────────────────────────────────────

EventCreateRequest = Annotated[
    SleepStartCreate
    | SleepEndCreate
    | FeedBreastCreate
    | FeedBottleCreate
    | PumpCreate
    | DiaperCreate
    | WeightCreate
    | TemperatureCreate
    | MedicationCreate
    | VaccinationCreate
    | DoctorVisitCreate
    | BathCreate
    | TummyTimeCreate
    | WalkCreate
    | SpitUpCreate
    | CryingCreate
    | GasCreate
    | FatherCalmingCreate
    | NoteCreate,
    Field(discriminator='type'),
]


# ── Response / request schemas ────────────────────────────────────────────────

class EventResponse(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    recorded_at: datetime
    type: EventType
    payload: dict
    raw_text: str | None
    source_type: str
    source_message_id: str | None
    source_chat_id: int | None
    parser_version: str | None

    model_config = {'from_attributes': True}


class FromTextRequest(BaseModel):
    text: str
    occurred_at: datetime
    source_type: str = 'telegram_live'
    source_message_id: str | None = None
    source_chat_id: int | None = None


class FromTextResponse(BaseModel):
    events: list[EventResponse]
    unparsed: str | None = None


class EventPatchRequest(BaseModel):
    occurred_at: datetime | None = None
    type: EventType | None = None
    payload: dict | None = None


# Maps EventType → its payload pydantic model (for PATCH re-validation)
_TYPE_TO_PAYLOAD_MODEL: dict[EventType, type[BaseModel]] = {
    EventType.sleep_start: SleepStartPayload,
    EventType.sleep_end: SleepEndPayload,
    EventType.feed_breast: FeedBreastPayload,
    EventType.feed_bottle: FeedBottlePayload,
    EventType.pump: PumpPayload,
    EventType.diaper: DiaperPayload,
    EventType.weight: WeightPayload,
    EventType.temperature: TemperaturePayload,
    EventType.medication: MedicationPayload,
    EventType.vaccination: VaccinationPayload,
    EventType.doctor_visit: DoctorVisitPayload,
    EventType.bath: BathPayload,
    EventType.tummy_time: TummyTimePayload,
    EventType.walk: WalkPayload,
    EventType.spit_up: SpitUpPayload,
    EventType.crying: CryingPayload,
    EventType.gas: GasPayload,
    EventType.father_calming: FatherCalmingPayload,
    EventType.note: NotePayload,
}


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    used_window: dict
    sources: list[uuid.UUID]


__all__ = [
    'BottleContents',
    'BreastSide',
    'CryingReason',
    'DiaperKind',
    'DoctorVisitType',
    'EventCreateRequest',
    'EventPatchRequest',
    'EventResponse',
    'FromTextRequest',
    'FromTextResponse',
    'AskRequest',
    'AskResponse',
    'SpitUpVolume',
    'TemperatureMethod',
    '_TYPE_TO_PAYLOAD_MODEL',
]
