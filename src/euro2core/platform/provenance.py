"""Digital certificate of a piece: a signed digest of its identity and provenance chain."""

import hashlib
import hmac
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.config import get_settings
from euro2core.domain.models import CoinIssue, CollectionItem
from euro2core.platform.portfolio import history


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def sign(digest: str, secret: str) -> str:
    return hmac.new(secret.encode(), digest.encode(), hashlib.sha256).hexdigest()


async def certificate_for(session: AsyncSession, item: CollectionItem) -> dict[str, Any]:
    issue = await session.get(CoinIssue, item.issue_id)
    events = await history(session, item.id)
    chain = [
        {
            "kind": e.kind,
            "from": str(e.from_user_id) if e.from_user_id else None,
            "to": str(e.to_user_id) if e.to_user_id else None,
            "price": str(e.price) if e.price is not None else None,
            "at": e.at.isoformat(),
        }
        for e in events
    ]
    payload = {
        "piece_id": str(item.id),
        "issue_id": str(item.issue_id),
        "type_id": str(issue.type_id) if issue else None,
        "grade": item.grade.value,
        "sheldon": item.sheldon,
        "verified_at": item.verified_at.isoformat() if item.verified_at else None,
        "chain": chain,
    }
    digest = _digest(payload)
    return {
        **payload,
        "digest": digest,
        "signature": sign(digest, get_settings().secret_key),
        "verify_url": f"/certificates/{item.id}/verify",
    }


async def verify_certificate(
    session: AsyncSession, item: CollectionItem, digest: str, signature: str
) -> dict[str, Any]:
    current = await certificate_for(session, item)
    expected_sig = sign(digest, get_settings().secret_key)
    return {
        "signature_valid": hmac.compare_digest(expected_sig, signature),
        "chain_unchanged": current["digest"] == digest,
        "current_digest": current["digest"],
        "events": len(current["chain"]),
    }
