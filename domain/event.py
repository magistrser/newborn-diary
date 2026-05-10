import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class EventType(StrEnum):
    # Sleep
    sleep_start = 'sleep_start'
    sleep_end = 'sleep_end'
    sleep_interval = 'sleep_interval'
    # Feeding
    feed_breast = 'feed_breast'
    feed_bottle = 'feed_bottle'
    pump = 'pump'
    # Diaper
    diaper = 'diaper'
    # Health & measurements
    weight = 'weight'
    temperature = 'temperature'
    medication = 'medication'
    vaccination = 'vaccination'
    doctor_visit = 'doctor_visit'
    # Baby activities
    bath = 'bath'
    tummy_time = 'tummy_time'
    walk = 'walk'
    # Symptoms
    spit_up = 'spit_up'
    crying = 'crying'
    gas = 'gas'
    # Other
    father_calming = 'father_calming'
    note = 'note'


class BreastSide(StrEnum):
    left = 'left'
    right = 'right'


class DiaperKind(StrEnum):
    pee = 'pee'
    poo = 'poo'
    both = 'both'
    unknown = 'unknown'


class BottleContents(StrEnum):
    formula = 'formula'
    expressed = 'expressed'


class TemperatureMethod(StrEnum):
    rectal = 'rectal'
    axillary = 'axillary'
    forehead = 'forehead'


class SpitUpVolume(StrEnum):
    small = 'small'
    large = 'large'


class CryingReason(StrEnum):
    hunger = 'hunger'
    gas = 'gas'
    unknown = 'unknown'


class DoctorVisitType(StrEnum):
    routine = 'routine'
    sick = 'sick'


# ── Payloads ──────────────────────────────────────────────────────────────────

class SleepStartPayload(BaseModel):
    pass


class SleepEndPayload(BaseModel):
    duration_min: int | None = None


class SleepIntervalPayload(BaseModel):
    started_at: datetime
    ended_at: datetime


class FeedBreastPayload(BaseModel):
    side: BreastSide
    duration_min: int | None = None


class FeedBottlePayload(BaseModel):
    volume_ml: int | None = None
    contents: BottleContents = BottleContents.formula


class PumpPayload(BaseModel):
    volume_ml: int | None = None
    duration_min: int | None = None


class DiaperPayload(BaseModel):
    kind: DiaperKind = DiaperKind.unknown


class WeightPayload(BaseModel):
    grams: int


class TemperaturePayload(BaseModel):
    celsius: float
    method: TemperatureMethod = TemperatureMethod.axillary


class MedicationPayload(BaseModel):
    name: str
    dose_ml: float | None = None


class VaccinationPayload(BaseModel):
    vaccine: str


class DoctorVisitPayload(BaseModel):
    type: DoctorVisitType = DoctorVisitType.routine
    notes: str | None = None


class BathPayload(BaseModel):
    duration_min: int | None = None


class TummyTimePayload(BaseModel):
    duration_min: int | None = None


class WalkPayload(BaseModel):
    duration_min: int | None = None


class SpitUpPayload(BaseModel):
    volume: SpitUpVolume = SpitUpVolume.small


class CryingPayload(BaseModel):
    duration_min: int | None = None
    reason: CryingReason = CryingReason.unknown


class GasPayload(BaseModel):
    pass


class FatherCalmingPayload(BaseModel):
    duration_min: int | None = None


class NotePayload(BaseModel):
    text: str


# ── Domain aggregate ──────────────────────────────────────────────────────────

class Event(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    recorded_at: datetime
    type: EventType
    payload: dict
    raw_text: str | None = None
    source_type: str
    source_message_id: str | None = None
    source_chat_id: int | None = None
    source_event_index: int = 0
    parser_version: str | None = None

    model_config = {'from_attributes': True}
