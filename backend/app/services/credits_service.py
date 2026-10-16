"""Credits ledger. Balances are always SUM(amount) over credit_transactions;
there is no separate mutable balance column that could drift."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .. import models
from . import config


def _lock_account(db: Session, role: str, account_id: int) -> None:
    """Serialize balance changes for one account (PostgreSQL runs requests in
    parallel; SQLite already serializes writers). Released at commit/rollback."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"credits:{role}:{account_id}"})


def balance(db: Session, role: str, account_id: int) -> int:
    total = (db.query(func.coalesce(func.sum(models.CreditTransaction.amount), 0))
             .filter(models.CreditTransaction.account_role == role,
                     models.CreditTransaction.account_id == account_id).scalar())
    return int(total or 0)


def find_by_reference(db: Session, role: str, account_id: int, reference: str) -> Optional[models.CreditTransaction]:
    return (db.query(models.CreditTransaction)
            .filter(models.CreditTransaction.account_role == role,
                    models.CreditTransaction.account_id == account_id,
                    models.CreditTransaction.reference == reference).first())


def add(db: Session, role: str, account_id: int, amount: int, type: str, description: str,
        reference: Optional[str] = None, commit: bool = True) -> models.CreditTransaction:
    """Append a ledger entry. With a reference it is idempotent."""
    _lock_account(db, role, account_id)
    if reference:
        existing = find_by_reference(db, role, account_id, reference)
        if existing:
            return existing
    new_balance = balance(db, role, account_id) + int(amount)
    row = models.CreditTransaction(account_role=role, account_id=account_id, amount=int(amount), type=type,
                                   description=description[:300], reference=reference, balance_after=new_balance)
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def spend(db: Session, role: str, account_id: int, feature: str, description: str,
          reference: Optional[str] = None, commit: bool = True) -> Optional[models.CreditTransaction]:
    """Debit the configured cost of ``feature``. 402 if the balance is too low.
    Returns None when the feature is free (cost 0)."""
    cost = config.CREDIT_COSTS.get(feature, 0)
    if cost <= 0:
        return None
    _lock_account(db, role, account_id)
    if reference:
        existing = find_by_reference(db, role, account_id, reference)
        if existing:
            return existing
    current = balance(db, role, account_id)
    if current < cost:
        raise HTTPException(status_code=402, detail=f"Not enough credits: {cost} needed, {current} available. Buy credits to continue.")
    return add(db, role, account_id, -cost, "spend", description, reference, commit=commit)


def grant_signup_bonus(db: Session, role: str, account_id: int) -> None:
    amount = config.HR_SIGNUP_CREDITS if role == "hr" else config.CANDIDATE_SIGNUP_CREDITS
    if amount > 0:
        add(db, role, account_id, amount, "signup_bonus", "Signup bonus", reference=f"signup:{role}:{account_id}")


def pack_price(credits: int) -> dict:
    price = credits * config.PRICE_PER_CREDIT_PAISE
    discount = price * config.EARLY_BIRD_PERCENT // 100 if config.early_bird_active() else 0
    return {"credits": credits, "price_paise": price, "discount_paise": discount, "amount_paise": price - discount}


def pricing() -> dict:
    return {
        "packs": [pack_price(c) for c in config.CREDIT_PACKS],
        "price_per_credit_paise": config.PRICE_PER_CREDIT_PAISE,
        "early_bird": {"active": config.early_bird_active(), "percent": config.EARLY_BIRD_PERCENT,
                       "until": config.EARLY_BIRD_UNTIL},
        "costs": config.CREDIT_COSTS,
        "hr_signup_credits": config.HR_SIGNUP_CREDITS,
        "payments_configured": config.payments_configured(),
    }
