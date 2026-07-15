from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Profile

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

DbSession = Annotated[Session, Depends(get_db)]


def require_profile(request: Request, db: DbSession) -> Profile:
    raw = request.cookies.get("profile_id")
    profile = db.get(Profile, int(raw)) if raw and raw.isdigit() else None
    if profile is None:
        if request.headers.get("HX-Request") == "true":
            # htmx follows redirects via XHR and would swap /profiles HTML into
            # the target div; HX-Redirect makes it do a full-page navigation.
            raise HTTPException(status_code=200, headers={"HX-Redirect": "/profiles"})
        # 303 (not 307) so a POST to a gated endpoint retries as GET /profiles
        # instead of re-POSTing its body to the wrong handler.
        raise HTTPException(status_code=303, headers={"Location": "/profiles"})
    return profile


CurrentProfile = Annotated[Profile, Depends(require_profile)]
