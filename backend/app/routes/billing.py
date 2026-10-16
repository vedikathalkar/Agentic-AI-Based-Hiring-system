"""Credits & billing: ledger, usage, pricing, Razorpay purchases, invoices."""

import base64
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, current_user
from ..services import config, credits_service
from ..services.notification_service import notify
from ..services.pdf_service import text_pdf
from fastapi.responses import Response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


def _account_user(user: Principal) -> Principal:
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Admins manage credits from the admin console")
    return user


def _month_range(month: Optional[str]) -> tuple[datetime, datetime, str]:
    now = datetime.utcnow()
    try:
        start = datetime.strptime(month, "%Y-%m") if month else datetime(now.year, now.month, 1)
    except ValueError:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    end = datetime(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return start, end, start.strftime("%B %Y")


def _tx_dict(t: models.CreditTransaction) -> dict:
    return {"transaction_id": t.transaction_id, "amount": t.amount, "type": t.type, "description": t.description,
            "balance_after": t.balance_after, "created_at": t.created_at}


@router.get("/pricing")
def pricing():
    return credits_service.pricing()


@router.get("/summary")
def summary(month: Optional[str] = None, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    user = _account_user(user)
    start, end, label = _month_range(month)
    q = db.query(models.CreditTransaction).filter(models.CreditTransaction.account_role == user.role,
                                                  models.CreditTransaction.account_id == user.id)
    in_month = q.filter(models.CreditTransaction.created_at >= start, models.CreditTransaction.created_at < end)
    prev_start = datetime(start.year - (start.month == 1), (start.month - 2) % 12 + 1, 1)
    prev_spent = -sum(t.amount for t in q.filter(models.CreditTransaction.created_at >= prev_start,
                                                 models.CreditTransaction.created_at < start,
                                                 models.CreditTransaction.amount < 0).all())
    rows = in_month.all()
    first = q.order_by(models.CreditTransaction.created_at).first()
    months = []
    if first:
        cursor = datetime(first.created_at.year, first.created_at.month, 1)
        now = datetime.utcnow()
        while cursor <= now:
            months.append(cursor.strftime("%Y-%m"))
            cursor = datetime(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return {
        "month": start.strftime("%Y-%m"), "month_label": label, "months": list(reversed(months)),
        "balance": credits_service.balance(db, user.role, user.id),
        "spent": -sum(t.amount for t in rows if t.amount < 0),
        "added": sum(t.amount for t in rows if t.amount > 0),
        "transactions": len(rows), "previous_month_spent": prev_spent,
        "costs": config.CREDIT_COSTS, "signup_credits": config.HR_SIGNUP_CREDITS if user.role == "hr" else config.CANDIDATE_SIGNUP_CREDITS,
    }


@router.get("/usage")
def usage(month: Optional[str] = None, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    """Where credits went in a month, grouped by feature."""
    user = _account_user(user)
    start, end, label = _month_range(month)
    rows = (db.query(models.CreditTransaction)
            .filter(models.CreditTransaction.account_role == user.role, models.CreditTransaction.account_id == user.id,
                    models.CreditTransaction.amount < 0, models.CreditTransaction.created_at >= start,
                    models.CreditTransaction.created_at < end).all())
    groups: dict[str, dict] = {}
    for t in rows:
        key = (t.reference or "other").split(":")[0]
        label_map = {"unlock": "Candidate unlocks", "assessment": "AI assessments", "offer": "Offer letters"}
        g = groups.setdefault(key, {"feature": label_map.get(key, "ATS checks" if "ATS" in (t.description or "") else "Other"),
                                    "credits": 0, "count": 0})
        g["credits"] += -t.amount
        g["count"] += 1
    return {"month_label": label, "total": sum(g["credits"] for g in groups.values()),
            "features": sorted(groups.values(), key=lambda g: -g["credits"])}


@router.get("/transactions")
def transactions(month: Optional[str] = None, type: Optional[str] = None, direction: Optional[str] = None,
                 q: Optional[str] = None, page: int = 1, size: int = 10,
                 user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    user = _account_user(user)
    query = db.query(models.CreditTransaction).filter(models.CreditTransaction.account_role == user.role,
                                                      models.CreditTransaction.account_id == user.id)
    if month:
        start, end, _ = _month_range(month)
        query = query.filter(models.CreditTransaction.created_at >= start, models.CreditTransaction.created_at < end)
    if type:
        query = query.filter(models.CreditTransaction.type == type)
    if direction == "credit":
        query = query.filter(models.CreditTransaction.amount > 0)
    elif direction == "debit":
        query = query.filter(models.CreditTransaction.amount < 0)
    if q:
        query = query.filter(func.lower(models.CreditTransaction.description).contains(q.lower()))
    total = query.count()
    size = min(100, max(5, size))
    page = max(1, page)
    rows = query.order_by(models.CreditTransaction.transaction_id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "pages": max(1, -(-total // size)),
            "items": [_tx_dict(t) for t in rows]}


# ---- Billing profile -------------------------------------------------------------

class BillingIn(BaseModel):
    billed_to: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    gst_number: Optional[str] = None


def _billing_profile(db: Session, user: Principal) -> models.BillingProfile:
    row = (db.query(models.BillingProfile)
           .filter(models.BillingProfile.account_role == user.role, models.BillingProfile.account_id == user.id).first())
    if row is None:
        company = db.query(models.Company).filter(models.Company.hr_account_id == user.id).first() if user.role == "hr" else None
        row = models.BillingProfile(account_role=user.role, account_id=user.id, billed_to=user.name, email=user.email,
                                    mobile=getattr(user.account, "phone", None),
                                    company=company.name if company else None,
                                    gst_number=company.gst_number if company else None)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _billing_dict(b: models.BillingProfile) -> dict:
    return {k: getattr(b, k) for k in ("billed_to", "company", "email", "mobile", "address", "gst_number")}


@router.get("/profile")
def get_billing_profile(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    return _billing_dict(_billing_profile(db, _account_user(user)))


@router.put("/profile")
def put_billing_profile(payload: BillingIn, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    b = _billing_profile(db, _account_user(user))
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(b, k, (v or "").strip() or None)
    b.updated_at = datetime.utcnow()
    db.commit()
    return _billing_dict(b)


# ---- Orders (Razorpay) -------------------------------------------------------------

class OrderIn(BaseModel):
    credits: int
    accept_terms: bool = False


class VerifyIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


def _order_dict(o: models.CreditOrder) -> dict:
    return {"order_id": o.order_id, "credits": o.credits, "price_paise": o.price_paise,
            "discount_paise": o.discount_paise, "amount_paise": o.amount_paise, "currency": o.currency,
            "status": o.status, "provider": o.provider, "provider_order_id": o.provider_order_id,
            "provider_payment_id": o.provider_payment_id, "invoice_number": o.invoice_number,
            "created_at": o.created_at, "paid_at": o.paid_at, "failure_reason": o.failure_reason}


def _razorpay_create(amount_paise: int, receipt: str, notes: dict) -> dict:
    key_id, secret = config.razorpay_keys()
    body = json.dumps({"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes}).encode()
    req = urllib.request.Request("https://api.razorpay.com/v1/orders", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Basic " + base64.b64encode(f"{key_id}:{secret}".encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        logger.error("Razorpay order creation failed: %s %s", exc.code, detail)
        raise HTTPException(status_code=502, detail="The payment provider rejected the order. Please try again later.")
    except OSError as exc:
        logger.exception("Razorpay unreachable")
        raise HTTPException(status_code=502, detail=f"Payment provider unreachable: {exc}")


@router.post("/orders")
def create_order(payload: OrderIn, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    user = _account_user(user)
    if payload.credits not in config.CREDIT_PACKS:
        raise HTTPException(status_code=422, detail=f"Choose one of the packs: {config.CREDIT_PACKS}")
    if not payload.accept_terms:
        raise HTTPException(status_code=422, detail="Accept the terms and refund policy to continue")
    if not config.payments_configured():
        raise HTTPException(status_code=503, detail="Online payments are not configured on this server yet. "
                                                    "Contact support to add credits.")
    price = credits_service.pack_price(payload.credits)
    billing = _billing_dict(_billing_profile(db, user))
    order = models.CreditOrder(account_role=user.role, account_id=user.id, credits=payload.credits,
                               price_paise=price["price_paise"], discount_paise=price["discount_paise"],
                               amount_paise=price["amount_paise"], status="created", provider="razorpay",
                               billing_snapshot=json.dumps(billing))
    db.add(order)
    db.commit()
    db.refresh(order)
    rp = _razorpay_create(order.amount_paise, f"hirelune-{order.order_id}",
                          {"account": f"{user.role}:{user.id}", "credits": str(order.credits)})
    order.provider_order_id = rp.get("id")
    db.commit()
    key_id, _ = config.razorpay_keys()
    return {**_order_dict(order), "key_id": key_id, "name": config.app_name(),
            "prefill": {"name": billing.get("billed_to"), "email": billing.get("email"), "contact": billing.get("mobile")}}


@router.post("/orders/{order_id}/verify")
def verify_order(order_id: int, payload: VerifyIn, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    user = _account_user(user)
    order = db.get(models.CreditOrder, order_id)
    if order is None or order.account_role != user.role or order.account_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status == "paid":
        return {**_order_dict(order), "balance": credits_service.balance(db, user.role, user.id)}
    if payload.razorpay_order_id != order.provider_order_id:
        raise HTTPException(status_code=422, detail="Order id mismatch")
    _, secret = config.razorpay_keys()
    expected = hmac.new(secret.encode(), f"{order.provider_order_id}|{payload.razorpay_payment_id}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        order.status, order.failure_reason = "failed", "Payment signature verification failed"
        db.commit()
        raise HTTPException(status_code=400, detail="Payment could not be verified")
    order.status, order.paid_at, order.provider_payment_id = "paid", datetime.utcnow(), payload.razorpay_payment_id
    order.invoice_number = f"HL-{order.paid_at:%Y%m}-{order.order_id:05d}"
    credits_service.add(db, user.role, user.id, order.credits, "purchase", f"Purchased {order.credits} credits",
                        reference=f"order:{order.order_id}", commit=False)
    db.commit()
    notify(db, user.role, user.id, "credits_purchased", "Credits added", f"{order.credits} credits were added to your account.",
           "/hr/billing" if user.role == "hr" else "/settings")
    return {**_order_dict(order), "balance": credits_service.balance(db, user.role, user.id)}


class FailIn(BaseModel):
    reason: Optional[str] = None


@router.post("/orders/{order_id}/fail")
def mark_failed(order_id: int, payload: FailIn, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    user = _account_user(user)
    order = db.get(models.CreditOrder, order_id)
    if order is None or order.account_role != user.role or order.account_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status == "created":
        order.status, order.failure_reason = "failed", (payload.reason or "Payment was cancelled")[:500]
        db.commit()
    return _order_dict(order)


@router.get("/orders")
def orders(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    user = _account_user(user)
    rows = (db.query(models.CreditOrder)
            .filter(models.CreditOrder.account_role == user.role, models.CreditOrder.account_id == user.id,
                    models.CreditOrder.status.in_(("paid", "failed")))
            .order_by(models.CreditOrder.order_id.desc()).all())
    paid = [o for o in rows if o.status == "paid"]
    return {"orders": [_order_dict(o) for o in rows],
            "totals": {"paid_paise": sum(o.amount_paise for o in paid), "credits": sum(o.credits for o in paid),
                       "invoices": len(paid), "last_payment": paid[0].paid_at if paid else None}}


@router.get("/invoices/{order_id}")
def invoice(order_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    order = db.get(models.CreditOrder, order_id)
    if order is None or order.status != "paid" or not (
            user.role == "admin" or (order.account_role == user.role and order.account_id == user.id)):
        raise HTTPException(status_code=404, detail="Invoice not found")
    b = json.loads(order.billing_snapshot or "{}")
    rupees = lambda p: f"Rs. {p / 100:,.2f}"  # noqa: E731
    body = "\n".join([
        f"Invoice number: {order.invoice_number}", f"Date: {order.paid_at:%d %B %Y}", "",
        "Billed to:", b.get("billed_to") or "", b.get("company") or "", b.get("address") or "",
        f"Email: {b.get('email') or '-'}   Mobile: {b.get('mobile') or '-'}", f"GSTIN: {b.get('gst_number') or 'Not provided'}", "",
        f"Item: {order.credits} {config.app_name()} credits", f"Price: {rupees(order.price_paise)}",
        f"Discount: -{rupees(order.discount_paise)}", f"Total paid: {rupees(order.amount_paise)}", "",
        f"Payment: Razorpay ({order.provider_payment_id})", f"Order: {order.provider_order_id}",
    ])
    pdf = text_pdf(f"{config.app_name()} — Tax Invoice", body, footer=order.invoice_number or "")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{order.invoice_number}.pdf"'})
