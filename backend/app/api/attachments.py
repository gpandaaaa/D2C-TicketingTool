import io
import re
import stat
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.entities import Attachment, User
from app.services.audit import audit
from app.services.tickets import get_ticket, notify

router = APIRouter()
MIMES = {
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "pdf": {"application/pdf"},
    "txt": {"text/plain"},
    "log": {"text/plain", "application/octet-stream"},
    "csv": {"text/csv", "text/plain", "application/vnd.ms-excel"},
    "zip": {"application/zip", "application/x-zip-compressed"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}


def validate(name, mime, content):
    ext = Path(name).suffix.lower().lstrip(".")
    if ext not in MIMES or mime not in MIMES[ext]:
        raise HTTPException(422, "Unsupported file type or MIME type")
    valid = True
    if ext == "png":
        valid = content.startswith(b"\x89PNG\r\n\x1a\n")
    elif ext in ("jpg", "jpeg"):
        valid = content.startswith(b"\xff\xd8\xff")
    elif ext == "pdf":
        valid = content.startswith(b"%PDF-")
    elif ext in ("txt", "log", "csv"):
        try:
            content.decode("utf-8")
            valid = b"\0" not in content
        except UnicodeDecodeError:
            valid = False
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                valid = (
                    len(entries) <= 1000 and sum(e.file_size for e in entries) <= 50 * 1024 * 1024
                )
                valid = valid and all(
                    not e.filename.startswith(("/", "\\"))
                    and ".." not in Path(e.filename.replace("\\", "/")).parts
                    and not (e.flag_bits & 1)
                    and not stat.S_ISLNK(e.external_attr >> 16)
                    for e in entries
                )
                names = archive.namelist()
                if ext == "docx":
                    valid = (
                        valid and "[Content_Types].xml" in names and "word/document.xml" in names
                    )
                if ext == "xlsx":
                    valid = valid and "[Content_Types].xml" in names and "xl/workbook.xml" in names
        except (zipfile.BadZipFile, ValueError):
            valid = False
    if not valid:
        raise HTTPException(
            422, "File content does not match its declared format or archive limits"
        )


@router.post("/tickets/{ticket_id}/attachments", status_code=201)
def upload(
    ticket_id: int,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    t = get_ticket(db, ticket_id, user, True)
    count = db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.ticket_id == ticket_id)
    )
    if count >= 100:
        raise HTTPException(422, "Ticket attachment limit reached")
    content = file.file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(422, "Empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "File exceeds 10 MB limit")
    name = re.sub(
        r"[^\w .()\-]",
        "_",
        Path((file.filename or "attachment").replace("\\", "/")).name,
    )[:200]
    validate(name, file.content_type, content)
    a = Attachment(ticket_id=t.id, author_id=user.id, name=name, size=len(content), content=content)
    db.add(a)
    db.flush()
    audit(
        db,
        user.id,
        "ATTACHMENT_UPLOADED",
        "ticket",
        t.id,
        after={"attachment_id": a.id, "name": name, "size": a.size},
    )
    notify(db, t, "ATTACHMENT_UPLOADED", "An attachment was uploaded")
    db.commit()
    return {"id": a.id, "name": a.name, "size": a.size}


@router.get("/tickets/{ticket_id}/attachments/{attachment_id}")
def download(
    ticket_id: int,
    attachment_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    get_ticket(db, ticket_id, user)
    a = db.scalar(
        select(Attachment).where(Attachment.id == attachment_id, Attachment.ticket_id == ticket_id)
    )
    if not a:
        raise HTTPException(404, "Attachment not found")
    return Response(
        a.content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(a.name)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
