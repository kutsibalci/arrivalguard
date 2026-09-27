"""İstek gövdeleri (pydantic). Doğrulama burada: dil, itinerary biçimi, rıza yöntemi, aksiyon adı."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..agent import COORDINATOR_ACTIONS, EVENT_TYPES, SUPPORTED_LANGUAGES


class Leg(BaseModel):
    country: int = Field(..., description="E.164 ülke kodu (ör. 90 Türkiye, 974 Katar)")
    eta: datetime
    label: str | None = None


class Itinerary(BaseModel):
    destination_country: int
    legs: list[Leg] = Field(..., min_length=1)

    @field_validator("legs")
    @classmethod
    def _dest_leg(cls, legs, info):
        dest = info.data.get("destination_country")
        if dest is not None and not any(leg.country == dest for leg in legs):
            raise ValueError("itinerary'de hedef ülke bacağı yok")
        return legs


class Contact(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    phone: str
    language: str = "en"
    plate: str | None = None
    id: str | None = None


class ConsentIn(BaseModel):
    """Klinik rızayı kendi sürecinde (ör. tedavi sözleşmesiyle birlikte imzalı form) aldıysa."""
    method: Literal["clinic_form", "signed_contract", "verbal_recorded"] = "clinic_form"
    text_version: str | None = None


class Zone(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    radius: float = Field(..., gt=0, le=50000)
    label: str | None = None


class CaseIn(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=120)
    patient_phone: str
    language: str = "en"
    clinic_id: str | None = None
    itinerary: Itinerary
    driver_id: str | None = None
    driver: Contact | None = None
    family_contact: Contact | None = None
    meeting_point: str | None = None
    zones: dict[str, Zone] | None = None
    consent: ConsentIn | None = None
    subscribe: bool = True

    @field_validator("language")
    @classmethod
    def _lang(cls, v):
        v = (v or "en").lower()[:2]
        if v not in SUPPORTED_LANGUAGES:
            raise ValueError(f"desteklenen diller: {', '.join(SUPPORTED_LANGUAGES)}")
        return v

    @field_validator("zones")
    @classmethod
    def _zones(cls, v):
        if v is not None and not {"airport", "corridor", "clinic"} <= set(v):
            raise ValueError("zones: airport, corridor, clinic üçü de gerekli")
        return v


class EventIn(BaseModel):
    type: str = Field(..., examples=list(EVENT_TYPES))
    now: datetime | None = None
    data: dict = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _type(cls, v):
        if v not in EVENT_TYPES or v in ("coordinator_action",):
            raise ValueError(f"olay tipi: {', '.join(t for t in EVENT_TYPES if t != 'coordinator_action')}")
        return v


class ActionIn(BaseModel):
    action: str
    alert_id: str | None = None
    reason: str | None = Field(None, max_length=500)
    text: str | None = Field(None, max_length=500)
    note: str | None = Field(None, max_length=200)
    driver_id: str | None = None
    driver: Contact | None = None

    @field_validator("action")
    @classmethod
    def _action(cls, v):
        if v not in COORDINATOR_ACTIONS:
            raise ValueError(f"aksiyon: {', '.join(COORDINATOR_ACTIONS)}")
        return v


class ConsentDecisionIn(BaseModel):
    decision: Literal["accept", "decline", "withdraw"]


class DriverVerifyIn(BaseModel):
    device_token: str | None = Field(None, description="Canlı: sürücü cihazının Number Verification OIDC token'ı. "
                                                       "Fixture/simülatör: 'sim-device:+90...'")


class ClinicIn(BaseModel):
    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9\-]{1,40}$")
    name: str = Field(..., min_length=1, max_length=120)
    language: str = "tr"
    meeting_point: str = ""
    zones: dict[str, Zone]
    drivers: list[Contact] = Field(default_factory=list)
    coordinator: dict = Field(default_factory=dict)


class DemoIn(BaseModel):
    reset: bool = True
    start: datetime | None = None
