"""Core data models shared by extraction, the rules engine, and the stores."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SourceKind(str, Enum):
    OEM = "oem"  # OEM manual / maintenance specification
    VENDOR = "vendor"  # Vendor contract / service schedule
    FIELD = "field"  # Service logs, work orders, field reports, emails


class IntervalUnit(str, Enum):
    HOURS = "hours"  # operating / run hours
    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"
    YEARS = "years"
    KM = "km"
    MILES = "miles"
    CYCLES = "cycles"  # starts, strokes, landings, etc.


class Interval(BaseModel):
    value: float = Field(gt=0)
    unit: IntervalUnit


class MaintenanceTask(BaseModel):
    """One maintenance requirement as stated by a single source document."""

    asset_id: str = Field(description="Equipment model or asset tag the task applies to")
    component: str = Field(description="Component or system, e.g. 'engine oil filter'")
    action: str = Field(description="Verb phrase, e.g. 'replace', 'inspect', 'lubricate'")
    part_ids: list[str] = Field(default_factory=list, description="OEM part numbers referenced")
    intervals: list[Interval] = Field(
        default_factory=list,
        description="All interval triggers; 'whichever comes first' becomes multiple entries",
    )
    source_quote: str = Field(default="", description="Verbatim text the task was extracted from")
    page: int | None = None


class ExtractionResult(BaseModel):
    """Schema handed to the OpenAI structured-output call."""

    tasks: list[MaintenanceTask]


class Document(BaseModel):
    doc_id: str
    filename: str
    kind: SourceKind
    asset_id: str
    vendor: str | None = None
    is_sample: bool = False  # True for synthetic pipeline-test data


class FindingType(str, Enum):
    MISSING_TASK = "missing_task"  # OEM task absent from vendor schedule
    EXTENDED_INTERVAL = "extended_interval"  # vendor interval longer than OEM
    MISSING_INTERVAL_BASIS = "missing_interval_basis"  # OEM has e.g. hours+months, vendor only months
    VENDOR_ADDITION = "vendor_addition"  # vendor does work the OEM does not require
    TIGHTENED_INTERVAL = "tightened_interval"  # vendor more frequent than OEM


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Finding(BaseModel):
    asset_id: str
    vendor: str | None
    type: FindingType
    severity: Severity
    task_key: str
    message: str
    oem_task: MaintenanceTask | None = None
    vendor_task: MaintenanceTask | None = None


class Rationale(BaseModel):
    """Why a vendor deviates from OEM (in the 'more than OEM' direction)."""

    asset_id: str
    vendor: str | None
    task_key: str
    rationale: str
    conditions: list[str] = Field(default_factory=list, description="e.g. 'heavy load', 'dust'")
    evidence: list[str] = Field(default_factory=list, description="Quotes from field docs")
    confidence: float = Field(ge=0, le=1)
