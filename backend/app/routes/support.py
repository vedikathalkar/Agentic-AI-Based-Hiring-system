from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, current_user
from ..services import files
from ..services.email_service import EmailService, dispatch_email
from ..services.hiring_context import link
from ..services.notification_service import notify, notify_admins

router = APIRouter(prefix="/support", tags=["support"])

CATEGORIES = ("Technical issue", "Application issue", "Assessment issue", "Interview issue", "Payment", "Account", "Other")
STATUSES = ("open", "in_progress", "resolved", "closed")


def _ticket_dict(t: models.SupportTicket, with_messages: bool = False) -> dict:
    out = {"ticket_id": t.ticket_id, "subject": t.subject, "category": t.category, "status": t.status,
           "name": t.name, "email": t.email, "requester_role": t.requester_role,
           "created_at": t.created_at, "updated_at": t.updated_at, "has_attachment": bool(t.attachment_path),
           "attachment_name": t.attachment_name, "message_count": len(t.messages)}
    if with_messages:
        out["messages"] = [{"message_id": m.message_id, "author_role": m.author_role, "author_name": m.author_name,
                            "body": m.body, "created_at": m.created_at} for m in t.messages]
    return out


def _get(db: Session, ticket_id: int, user: Principal) -> models.SupportTicket:
    t = db.get(models.SupportTicket, ticket_id)
    if t is None or not (user.role == "admin" or (t.requester_role == user.role and t.requester_id == user.id)):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@router.get("/categories")
def categories():
    return {"categories": list(CATEGORIES), "statuses": list(STATUSES)}


@router.post("/tickets")
async def create_ticket(background: BackgroundTasks, subject: str = Form(..., min_length=3, max_length=200),
                        message: str = Form(..., min_length=5), category: str = Form("Other"),
                        name: Optional[str] = Form(None), email: Optional[str] = Form(None),
                        attachment: Optional[UploadFile] = File(None),
                        user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Admins answer tickets from the admin console")
    if category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"category must be one of: {', '.join(CATEGORIES)}")
    t = models.SupportTicket(requester_role=user.role, requester_id=user.id, name=(name or user.name).strip(),
                             email=(email or user.email or "").strip(), category=category, subject=subject.strip(),
                             status="open", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    if attachment is not None and attachment.filename:
        t.attachment_path, t.attachment_name = await files.save_upload(attachment, "support",
                                                                       files.IMAGE_EXT + files.DOC_EXT + (".txt",))
    t.messages.append(models.SupportMessage(author_role=user.role, author_name=t.name, body=message.strip()))
    db.add(t)
    db.commit()
    db.refresh(t)
    notify_admins(db, "support_ticket", f"New ticket #{t.ticket_id}", f"{t.category}: {t.subject}", "/admin/support")
    log = EmailService.queue(db, to=t.email, subject=f"[Ticket #{t.ticket_id}] {t.subject}", template="support_ticket",
                             context={"recipient_name": t.name, "intro": "We received your request and will get back to you soon.",
                                      "ticket_id": t.ticket_id, "ticket_subject": t.subject, "status_label": "Open",
                                      "message": None, "link": link("/support" if user.role == "candidate" else "/hr/support")},
                             related_type="ticket", related_id=t.ticket_id, recipient_role=user.role, recipient_id=user.id)
    if log:
        background.add_task(dispatch_email, log.email_id)
    return _ticket_dict(t, True)


@router.get("/tickets")
def list_tickets(status: Optional[str] = None, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.SupportTicket)
    if user.role != "admin":
        q = q.filter(models.SupportTicket.requester_role == user.role, models.SupportTicket.requester_id == user.id)
    if status:
        q = q.filter(models.SupportTicket.status == status)
    return [_ticket_dict(t) for t in q.order_by(models.SupportTicket.updated_at.desc().nullslast()).all()]


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    return _ticket_dict(_get(db, ticket_id, user), True)


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


@router.post("/tickets/{ticket_id}/messages")
def reply(ticket_id: int, payload: ReplyIn, background: BackgroundTasks, user: Principal = Depends(current_user),
          db: Session = Depends(get_db)):
    t = _get(db, ticket_id, user)
    if t.status == "closed" and user.role != "admin":
        raise HTTPException(status_code=409, detail="This ticket is closed. Open a new ticket if you still need help.")
    t.messages.append(models.SupportMessage(author_role=user.role, author_name=user.name if user.role != "admin" else "Hirelune Support",
                                            body=payload.body.strip()))
    t.updated_at = datetime.utcnow()
    if user.role == "admin":
        if t.status == "open":
            t.status = "in_progress"
        db.commit()
        notify(db, t.requester_role, t.requester_id, "support_update", f"Reply on ticket #{t.ticket_id}", t.subject,
               "/support" if t.requester_role == "candidate" else "/hr/support")
        log = EmailService.queue(db, to=t.email, subject=f"[Ticket #{t.ticket_id}] New reply", template="support_ticket",
                                 context={"recipient_name": t.name, "intro": "Our support team replied to your ticket.",
                                          "ticket_id": t.ticket_id, "ticket_subject": t.subject,
                                          "status_label": t.status.replace("_", " ").title(), "message": payload.body,
                                          "link": link("/support" if t.requester_role == "candidate" else "/hr/support")},
                                 related_type="ticket", related_id=t.ticket_id,
                                 recipient_role=t.requester_role, recipient_id=t.requester_id)
        if log:
            background.add_task(dispatch_email, log.email_id)
    else:
        if t.status in ("resolved",):
            t.status = "open"
        db.commit()
        notify_admins(db, "support_ticket", f"Reply on ticket #{t.ticket_id}", t.subject, "/admin/support")
    return _ticket_dict(t, True)


class StatusIn(BaseModel):
    status: Literal["open", "in_progress", "resolved", "closed"]


@router.patch("/tickets/{ticket_id}/status")
def set_status(ticket_id: int, payload: StatusIn, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    t = _get(db, ticket_id, user)
    if user.role != "admin" and payload.status not in ("closed", "open"):
        raise HTTPException(status_code=403, detail="You can close or re-open your own ticket")
    t.status, t.updated_at = payload.status, datetime.utcnow()
    db.commit()
    if user.role == "admin":
        notify(db, t.requester_role, t.requester_id, "support_update", f"Ticket #{t.ticket_id} is {payload.status.replace('_', ' ')}",
               t.subject, "/support" if t.requester_role == "candidate" else "/hr/support")
    return _ticket_dict(t, True)


@router.get("/tickets/{ticket_id}/attachment")
def attachment(ticket_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    t = _get(db, ticket_id, user)
    return files.file_response(t.attachment_path, t.attachment_name)
