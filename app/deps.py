import hashlib
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Profile

_APP_DIR = Path(__file__).parent

templates = Jinja2Templates(directory=_APP_DIR / "templates")

_static_versions: dict[str, str] = {}


def static_url(path: str) -> str:
    """/static URL with a content-hash query param so browsers re-fetch
    changed CSS/JS after a deploy instead of serving a stale cached copy."""
    v = _static_versions.get(path)
    if v is None:
        file = _APP_DIR / "static" / path.lstrip("/")
        v = hashlib.md5(file.read_bytes()).hexdigest()[:8] if file.is_file() else "0"
        _static_versions[path] = v
    return f"/static/{path.lstrip('/')}?v={v}"


templates.env.globals["static_url"] = static_url

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
