"""Price alerts: notify Pro users when a valuation crosses their threshold."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import Grade
from euro2core.domain.models import Notification, PriceAlert
from euro2core.platform.valuation import valuations_for


async def check_alerts(session: AsyncSession) -> dict[str, int]:
    alerts = (await session.scalars(select(PriceAlert).where(PriceAlert.active.is_(True)))).all()
    values = await valuations_for(session, [(a.issue_id, Grade.UNKNOWN) for a in alerts])
    fired = 0
    for alert in alerts:
        valuation = values[(alert.issue_id, Grade.UNKNOWN)]
        if valuation.basis == "face_value":
            continue  # no market evidence yet
        hit = (alert.direction == "above" and valuation.value >= alert.threshold) or (
            alert.direction == "below" and valuation.value <= alert.threshold
        )
        if not hit:
            continue
        alert.active = False
        session.add(
            Notification(
                user_id=alert.user_id,
                kind="price_alert",
                title=(
                    f"Alerta de precio: {valuation.value} € ({alert.direction} {alert.threshold} €)"
                ),
                body=(
                    f"Price alert: {valuation.value} EUR ({alert.direction} {alert.threshold} EUR)"
                ),
                payload={
                    "issue_id": str(alert.issue_id),
                    "value": str(valuation.value),
                    "basis": valuation.basis,
                    "threshold": str(alert.threshold),
                    "direction": alert.direction,
                },
            )
        )
        fired += 1
    await session.flush()
    return {"alerts_checked": len(alerts), "alerts_fired": fired}
