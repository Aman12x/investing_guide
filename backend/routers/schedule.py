import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Subscription
from schemas import SubscriptionConfig

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/schedule", status_code=201)
async def upsert_subscription(config: SubscriptionConfig, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subscription).where(Subscription.email == config.email))
    sub = result.scalar_one_or_none()

    if sub:
        sub.tickers = config.tickers
        sub.schedule = config.schedule
        sub.format = config.format
        sub.active = True
    else:
        sub = Subscription(
            email=config.email,
            tickers=config.tickers,
            schedule=config.schedule,
            format=config.format,
        )
        db.add(sub)

    await db.commit()
    logger.info("Subscription upserted for %s", config.email)
    return {"message": "subscription saved", "email": config.email}


@router.get("/schedule")
async def get_subscription(email: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subscription).where(Subscription.email == email, Subscription.active == True))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(
            status_code=404,
            detail={"error": "No active subscription for that email", "code": "SUBSCRIPTION_NOT_FOUND"},
        )
    return {
        "email": sub.email,
        "tickers": sub.tickers,
        "schedule": sub.schedule,
        "format": sub.format,
        "active": sub.active,
    }


@router.delete("/schedule")
async def cancel_subscription(email: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subscription).where(Subscription.email == email))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(
            status_code=404,
            detail={"error": "No subscription for that email", "code": "SUBSCRIPTION_NOT_FOUND"},
        )
    sub.active = False
    await db.commit()
    logger.info("Subscription cancelled for %s", email)
    return {"message": "subscription cancelled", "email": email}
