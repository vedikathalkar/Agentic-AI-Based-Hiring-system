"""Refer & Earn. Rewards are credited to the referrer's credits ledger only after
the referred candidate completes their first assessment (the qualifying event)."""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from .. import models
from . import config, credits_service
from .notification_service import notify

QUALIFYING_EVENT = "Your friend signs up with your link and completes their first assessment."


def get_or_create_code(db: Session, account: models.CandidateAccount) -> models.ReferralCode:
    row = db.query(models.ReferralCode).filter(models.ReferralCode.account_id == account.account_id).first()
    if row:
        return row
    stem = re.sub(r"[^A-Z]", "", (account.name or "USER").upper())[:4] or "USER"
    for _ in range(20):
        code = f"HIRL-{stem}-{secrets.randbelow(9000) + 1000}"
        if not db.query(models.ReferralCode).filter(models.ReferralCode.code == code).first():
            break
    row = models.ReferralCode(code=code, account_id=account.account_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def register_signup(db: Session, new_account: models.CandidateAccount, code: Optional[str]) -> Optional[models.Referral]:
    if not code:
        return None
    ref = db.query(models.ReferralCode).filter(models.ReferralCode.code == code.strip().upper()).first()
    if ref is None or ref.account_id == new_account.account_id:
        return None
    if db.query(models.Referral).filter(models.Referral.referred_account_id == new_account.account_id).first():
        return None
    row = models.Referral(code_id=ref.code_id, referrer_account_id=ref.account_id,
                          referred_account_id=new_account.account_id, status="signed_up")
    new_account.referred_by_code = ref.code
    db.add(row)
    db.commit()
    notify(db, "candidate", ref.account_id, "referral_signup", "A friend joined with your link",
           f"{new_account.name} signed up. You'll earn {config.REFERRAL_REWARD_CREDITS} credits when they complete their first assessment.",
           "/refer")
    return row


def qualify(db: Session, referred_account_id: Optional[int]) -> Optional[models.Referral]:
    if not referred_account_id:
        return None
    row = (db.query(models.Referral)
           .filter(models.Referral.referred_account_id == referred_account_id,
                   models.Referral.status == "signed_up").first())
    if row is None:
        return None
    now = datetime.utcnow()
    row.status, row.qualified_at = "qualified", now
    reward = config.REFERRAL_REWARD_CREDITS
    if reward > 0:
        credits_service.add(db, "candidate", row.referrer_account_id, reward, "referral_reward",
                            "Referral reward", reference=f"referral:{row.referral_id}", commit=False)
        row.status, row.reward_credits, row.rewarded_at = "rewarded", reward, now
    db.commit()
    notify(db, "candidate", row.referrer_account_id, "referral_reward", "Referral reward earned",
           f"You earned {reward} credits.", "/refer")
    return row


def summary(db: Session, account: models.CandidateAccount) -> dict:
    code = get_or_create_code(db, account)
    rows = (db.query(models.Referral).filter(models.Referral.referrer_account_id == account.account_id)
            .order_by(models.Referral.created_at.desc().nullslast()).all())
    people = []
    for r in rows:
        friend = db.get(models.CandidateAccount, r.referred_account_id)
        name = (friend.name if friend else "Friend") or "Friend"
        people.append({"referral_id": r.referral_id, "name": name.split()[0], "status": r.status,
                       "reward_credits": r.reward_credits, "created_at": r.created_at, "rewarded_at": r.rewarded_at})
    return {
        "code": code.code, "link": f"{config.frontend_url()}/signup?ref={code.code}",
        "reward_per_referral": config.REFERRAL_REWARD_CREDITS, "qualifying_event": QUALIFYING_EVENT,
        "successful": sum(1 for r in rows if r.status == "rewarded"),
        "pending": sum(1 for r in rows if r.status in ("signed_up", "qualified")),
        "credits_earned": sum(r.reward_credits or 0 for r in rows),
        "credit_balance": credits_service.balance(db, "candidate", account.account_id),
        "referrals": people,
    }
