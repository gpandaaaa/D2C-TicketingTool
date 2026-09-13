from pydantic import BaseModel, EmailStr, Field

from app.models.entities import Priority, Role, TicketStatus


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    role: Role
    department: str | None = None
    active: bool


class TicketIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    priority: Priority = Priority.MEDIUM
    category_id: int | None = None
    asset_id: int | None = None
    kind: str = "INC"


class TicketUpdate(BaseModel):
    status: TicketStatus | None = None
    priority: Priority | None = None
    assignee_id: int | None = None
    team: str | None = None
    asset_id: int | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    internal: bool = False


class AssetIn(BaseModel):
    asset_type: str = Field(min_length=2, max_length=80)
    serial_number: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    hostname: str | None = None
    department: str | None = None
    location: str | None = None
    notes: str | None = None


class AssetAssign(BaseModel):
    user_id: int | None = None


class ArticleIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    category: str
    content: str = Field(min_length=1)
    tags: str = ""
    published: bool = False
