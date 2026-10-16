from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models

SETTING_FIELDS = (
    "theme", "email_notifications", "assessment_notifications", "interview_notifications",
    "reminder_notifications", "offer_notifications", "marketing_notifications",
    "profile_visibility", "resume_visibility", "allow_data_for_matching",
)


def get_settings(db: Session, role: str, account_id: int) -> models.UserSettings:
    row = (db.query(models.UserSettings)
           .filter(models.UserSettings.role == role, models.UserSettings.account_id == account_id).first())
    if row is None:
        row = models.UserSettings(role=role, account_id=account_id, theme="dark", email_notifications=True,
                                  assessment_notifications=True, interview_notifications=True,
                                  reminder_notifications=True, offer_notifications=True,
                                  marketing_notifications=False, profile_visibility="employers",
                                  resume_visibility="applied", allow_data_for_matching=True)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:          # a parallel request created it first
            db.rollback()
            return db.query(models.UserSettings).filter(models.UserSettings.role == role, models.UserSettings.account_id == account_id).one()
        db.refresh(row)
    return row


def settings_dict(row: models.UserSettings) -> dict:
    return {f: getattr(row, f) for f in SETTING_FIELDS} | {"updated_at": row.updated_at}


def update_settings(db: Session, role: str, account_id: int, changes: dict) -> models.UserSettings:
    row = get_settings(db, role, account_id)
    for key, value in changes.items():
        if key in SETTING_FIELDS and value is not None:
            setattr(row, key, value)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row
