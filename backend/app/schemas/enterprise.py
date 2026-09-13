from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.entities import Priority, Role, TicketStatus


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def strip_text(cls, value, info):
        if isinstance(value, str) and info.field_name not in (
            "password",
            "current_password",
        ):
            value = value.strip()
            if not value and info.field_name in (
                "employee_id",
                "department",
                "team",
                "phone",
                "location",
            ):
                return None
            return value
        return value


class Login(Input):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class Password(Input):
    password: str = Field(min_length=12, max_length=128)
    current_password: str | None = None


class UserCreate(Input):
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=255)
    employee_id: str | None = Field(None, max_length=64)
    team: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=128)
    role: Role = Role.USER
    department: str | None = Field(None, max_length=120)
    location: str | None = Field(None, max_length=120)


class UserEdit(Input):
    email: str | None = Field(None, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=255)
    employee_id: str | None = Field(None, max_length=64)
    team: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=40)
    name: str | None = Field(None, min_length=2, max_length=160)
    role: Role | None = None
    department: str | None = Field(None, max_length=120)
    location: str | None = Field(None, max_length=120)
    active: bool | None = None


class EngineerEdit(Input):
    subskills: list[int] = Field(default_factory=list, max_length=100)
    available: bool = True
    capacity: int = Field(10, ge=1, le=1000)
    skills: list[int] = Field(default_factory=list, max_length=100)


class TicketCreate(Input):
    location: str | None = Field(None, max_length=120)
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    priority: Priority = Priority.MEDIUM
    category_id: int
    subcategory_id: int | None = None
    team: str | None = Field(None, max_length=100)


class TicketEdit(Input):
    title: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = Field(None, min_length=1, max_length=10000)
    priority: Priority | None = None
    category_id: int | None = None
    subcategory_id: int | None = None
    status: TicketStatus | None = None
    resolution: str | None = Field(None, max_length=10000)
    team: str | None = Field(None, max_length=100)


class Assignment(Input):
    engineer_id: int | None
    reason: str = Field("Manual assignment", min_length=1, max_length=1000)


class CategoryEdit(Input):
    name: str = Field(min_length=2, max_length=100)
    active: bool = True


class SubcategoryEdit(CategoryEdit):
    category_id: int


class SLAEdit(Input):
    response_minutes: int = Field(ge=1, le=525600)
    resolution_minutes: int = Field(ge=1, le=525600)


class AssignmentRules(Input):
    urgency_weight: int = Field(10, ge=0, le=100)
    category_weight: int = Field(40, ge=0, le=100)
    subcategory_weight: int = Field(25, ge=0, le=100)
    location_weight: int = Field(15, ge=0, le=100)
    team_weight: int = Field(10, ge=0, le=100)
    workload_weight: int = Field(10, ge=0, le=100)
    enabled: bool = True
    fallback: bool = False
    strategy: str = Field("least_workload", pattern="^(least_workload|round_robin|scored)$")


class WorkflowConfig(Input):
    reopen_days: int = Field(7, ge=0, le=365)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("labels")
    @classmethod
    def labels_valid(cls, v):
        allowed = {s.value for s in TicketStatus} | {p.value for p in Priority}
        if any(k not in allowed or not 1 <= len(val) <= 60 for k, val in v.items()):
            raise ValueError("Invalid status or priority label")
        return v


class BulkAction(Input):
    resolution: str | None = Field(None, max_length=10000)
    ids: list[int] = Field(min_length=1, max_length=100)
    action: str = Field(pattern="^(assign|priority|status)$")
    engineer_id: int | None = None
    priority: Priority | None = None
    status: TicketStatus | None = None
    reason: str = Field("Bulk update", max_length=1000)


class NotificationRules(Input):
    enabled: bool = True
    sla_warning_minutes: int = Field(60, ge=1, le=1440)
