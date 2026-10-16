from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import Principal, require_candidate
from ..services import referral_service

router = APIRouter(prefix="/referrals", tags=["referrals"])


@router.get("")
def my_referrals(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    return referral_service.summary(db, user.account)


@router.post("")
def create_code(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    """Generates (once) and returns the candidate's referral code/link."""
    referral_service.get_or_create_code(db, user.account)
    return referral_service.summary(db, user.account)
