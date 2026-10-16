from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, current_user
from ..services.notification_service import unread_count

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _mine(db: Session, user: Principal):
    return db.query(models.Notification).filter(models.Notification.recipient_role == user.role,
                                                models.Notification.recipient_id == user.id)


@router.get("")
def list_notifications(limit: int = 30, unread_only: bool = False, user: Principal = Depends(current_user),
                       db: Session = Depends(get_db)):
    q = _mine(db, user)
    if unread_only:
        q = q.filter(models.Notification.read.is_(False))
    rows = q.order_by(models.Notification.notification_id.desc()).limit(min(100, max(1, limit))).all()
    return {"unread": unread_count(db, user.role, user.id),
            "items": [{"notification_id": n.notification_id, "type": n.type, "title": n.title, "message": n.message,
                       "link": n.link, "read": bool(n.read), "created_at": n.created_at} for n in rows]}


@router.get("/unread-count")
def count(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    return {"unread": unread_count(db, user.role, user.id)}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    n = _mine(db, user).filter(models.Notification.notification_id == notification_id).first()
    if n is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.read = True
    db.commit()
    return {"unread": unread_count(db, user.role, user.id)}


@router.post("/read-all")
def mark_all(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    _mine(db, user).filter(models.Notification.read.is_(False)).update({"read": True}, synchronize_session=False)
    db.commit()
    return {"unread": 0}
