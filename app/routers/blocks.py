from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from app.deps import CurrentProfile, DbSession, templates
from app.models import Deck
from app.routers.profiles import block_stats
from app.routers.study import MODES_BY_KIND

router = APIRouter(prefix="/blocks")


@router.get("/{deck_id}")
def block_detail(
    deck_id: int, request: Request, db: DbSession, profile: CurrentProfile, empty: str | None = None
):
    deck = db.get(Deck, deck_id)
    if deck is None:
        raise HTTPException(404, "Block not found")
    now = datetime.now(timezone.utc)
    stats = block_stats(db, profile.id, deck, now)
    modes = sorted(MODES_BY_KIND.get(deck.kind, MODES_BY_KIND["vocab"])) + ["random"]
    return templates.TemplateResponse(
        request,
        "blocks.html",
        {
            "profile": profile,
            "deck": deck,
            "total": stats["total"],
            "started": stats["started"],
            "due": stats["due"],
            "modes": modes,
            "empty": bool(empty),
        },
    )
