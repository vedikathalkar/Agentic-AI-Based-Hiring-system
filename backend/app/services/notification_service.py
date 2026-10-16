"""In-app notifications (persisted; the bell reads them from the API)."""

from typing import Optional

from sqlalchemy.orm import Session

from .. import models


def notify(db: Session, role: str, account_id: Optional[int], type: str, title: str,
           message: str = "", link: Optional[str] = None, commit: bool = True) -> Optional[models.Notification]:
    if not role or not account_id:
        return None
    row = models.Notification(recipient_role=role, recipient_id=account_id, type=type,
                              title=title[:200], message=message, link=link)
    db.add(row)
    if commit:
        db.commit()
    return row


def notify_admins(db: Session, type: str, title: str, message: str = "", link: Optional[str] = None) -> None:
    for admin in db.query(models.AdminAccount).all():
        notify(db, "admin", admin.admin_id, type, title, message, link, commit=False)
    db.commit()


def unread_count(db: Session, role: str, account_id: int) -> int:
    return (db.query(models.Notification)
            .filter(models.Notification.recipient_role == role,
                    models.Notification.recipient_id == account_id,
                    models.Notification.read.is_(False)).count())
