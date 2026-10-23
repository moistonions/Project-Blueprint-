"""Core data models shared by extraction, the rules engine, and the stores."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class SourceKind(str, Enum):
    OEM = "oem"  # OEM manual / maintenance specification
    VENDOR = "vendor"  # Vendor contract / service schedule
    FIELD = "field"  # Free-text field material: emails, reports


class BaselineStatus(str, Enum):
    """OEM task lists must be signed off by a person before any comparison runs."""

    DRAFT = "draft"
    APPROVED = "approved"


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


# Defaults below use default_factory so no "default" keys reach the OpenAI strict JSON schema.
class ExtractedTask(BaseModel):
    """One maintenance requirement as stated by a single source document (LLM output schema)."""

    asset_id: str = Field(description="Equipment model or asset tag the task applies to")
    component: str = Field(description="Component or system, e.g. 'engine oil filter'")
    action: str = Field(description="Verb phrase, e.g. 'replace', 'inspect', 'lubricate'")
    part_ids: list[str] = Field(default_factory=list, description="OEM part numbers referenced")
    spec: str | None = Field(default=None, description="Fluid or material spec, e.g. 'SAE 15W-40'")
    intervals: list[Interval] = Field(
        default_factory=list,
        description="All interval triggers; 'whichever comes first' becomes multiple entries",
    )
    source_quote: str = Field(default_factory=str, description="Verbatim text the task was extracted from")
    page: int | None = None
    needs_review: bool = Field(
        default_factory=bool,
        description="True when the source is unclear: blurry table, 'as required', ambiguous interval",
    )
    review_note: str = Field(default_factory=str, description="Why the extraction needs review")


class MaintenanceTask(ExtractedTask):
    id: int | None = None  # database row id
    safety_critical: bool = False  # set by a person at baseline sign-off; zero tolerance


class ExtractionResult(BaseModel):
    """Schema handed to the OpenAI structured-output call."""

    tasks: list[ExtractedTask]


class Document(BaseModel):
    doc_id: str
    filename: str
    kind: SourceKind
    asset_id: str
    vendor: str | None = None
    is_sample: bool = False  # True for synthetic, clearly labelled test data
    baseline_status: BaselineStatus = BaselineStatus.DRAFT  # meaningful for OEM docs only


class Ticket(BaseModel):
    """One completed checklist line submitted by a vendor."""

    asset_id: str
    vendor: str | None = None
    date: date
    component: str
    action: str
    meter_hours: float | None = Field(default=None, description="Asset hour-meter reading at the visit")
    time_spent_hours: float | None = None
    notes: str = ""
    is_sample: bool = False

    def as_task(self) -> MaintenanceTask:
        return MaintenanceTask(asset_id=self.asset_id, component=self.component, action=self.action)


class FindingType(str, Enum):
    MISSING_TASK = "missing_task"  # OEM task absent from vendor schedule
    LONGER_INTERVAL = "longer_interval"  # vendor interval longer than OEM, within tolerance
    BEYOND_TOLERANCE = "beyond_tolerance"  # vendor interval longer than OEM beyond tolerance
    MISSING_INTERVAL_BASIS = "missing_interval_basis"  # OEM has e.g. hours+months, vendor only months
    SPEC_MISMATCH = "spec_mismatch"  # different part number or fluid spec (ambiguous)
    EXECUTION_GAP = "execution_gap"  # tickets show the task done late or skipped
    NEEDS_REVIEW = "needs_review"  # unresolved uncertain extraction; counts as failed
    VENDOR_ADDITION = "vendor_addition"  # vendor does work the OEM does not require
    TIGHTENED_INTERVAL = "tightened_interval"  # vendor more frequent than OEM


# Findings that represent a compliance gap (vs. informational "vendor does more").
GAP_TYPES = {
    FindingType.MISSING_TASK,
    FindingType.LONGER_INTERVAL,
    FindingType.BEYOND_TOLERANCE,
    FindingType.MISSING_INTERVAL_BASIS,
    FindingType.SPEC_MISMATCH,
    FindingType.EXECUTION_GAP,
    FindingType.NEEDS_REVIEW,
}


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class MatchBasis(str, Enum):
    TASK_KEY = "same task"
    PART_NUMBER = "shared part number"
    SIMILAR_NAME = "similar component name"


class Finding(BaseModel):
    asset_id: str
    vendor: str | None
    type: FindingType
    severity: Severity
    task_key: str
    message: str
    oem_task: MaintenanceTask | None = None
    vendor_task: MaintenanceTask | None = None
    match_basis: MatchBasis | None = None
    match_confidence: float | None = None


class ExtraWorkStatus(str, Enum):
    JUSTIFIED = "justified"
    UNJUSTIFIED = "unjustified"
    UNKNOWN = "unknown"


class Rationale(BaseModel):
    """Why a vendor deviates from OEM (in the 'more than OEM' direction)."""

    asset_id: str
    vendor: str | None
    task_key: str
    rationale: str
    status: ExtraWorkStatus
    confirmed: bool = Field(description="True only when backed by a verbatim source quote")
    conditions: list[str] = Field(default_factory=list, description="e.g. 'heavy load', 'dust'")
    evidence: list[str] = Field(default_factory=list, description="Verified quotes from field docs")
    confidence: float = Field(ge=0, le=1)
