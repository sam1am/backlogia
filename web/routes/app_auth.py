# routes/app_auth.py
# Login, setup, and logout routes for optional authentication

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeSerializer, URLSafeTimedSerializer

from ..config import ENABLE_AUTH, SECRET_KEY
from ..services.auth_service import (
    user_exists,
    create_user,
    verify_user,
    create_session,
    delete_session,
    get_or_create_secret_key,
)

router = APIRouter(tags=["App Auth"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def _get_signer():
    """Get the URL-safe signer using the configured secret key."""
    actual_secret = SECRET_KEY or get_or_create_secret_key()
    return URLSafeSerializer(actual_secret, salt="backlogia-session")


def _generate_csrf_token() -> str:
    """Generate a signed, time-limited CSRF token (expires in 1 hour)."""
    actual_secret = SECRET_KEY or get_or_create_secret_key()
    s = URLSafeTimedSerializer(actual_secret, salt="backlogia-csrf")
    return s.dumps("csrf")


def _validate_csrf_token(token: str) -> bool:
    """Validate a CSRF token. Returns False if missing, expired, or tampered."""
    if not token:
        return False
    try:
        actual_secret = SECRET_KEY or get_or_create_secret_key()
        s = URLSafeTimedSerializer(actual_secret, salt="backlogia-csrf")
        s.loads(token, max_age=3600)
        return True
    except (BadSignature, SignatureExpired):
        return False


def _set_session_cookie(response, session_id):
    """Set the signed session cookie on the response."""
    signer = _get_signer()
    signed = signer.dumps(session_id)
    response.set_cookie(
        key="backlogia_session",
        value=signed,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,
    )
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    """Render the login page."""
    if not ENABLE_AUTH:
        return RedirectResponse(url="/", status_code=303)

    if not user_exists():
        return RedirectResponse(url="/setup", status_code=303)

    return templates.TemplateResponse(
        request,
        "login.html",
        {"next": next, "error": "", "csrf_token": _generate_csrf_token()},
    )


@router.post("/auth/login")
def auth_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
    csrf_token: str = Form(default=""),
):
    """Handle login form submission."""
    if not _validate_csrf_token(csrf_token):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "error": "Invalid or expired form token. Please try again.", "csrf_token": _generate_csrf_token()},
            status_code=403,
        )

    user = verify_user(username, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "error": "Invalid username or password", "csrf_token": _generate_csrf_token()},
            status_code=401,
        )

    session_id = create_session(user["id"])
    redirect_to = next if next else "/"
    response = RedirectResponse(url=redirect_to, status_code=303)
    _set_session_cookie(response, session_id)
    return response


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    """Render the account setup page (only if no user exists)."""
    if not ENABLE_AUTH:
        return RedirectResponse(url="/", status_code=303)

    if user_exists():
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "setup.html",
        {"error": "", "csrf_token": _generate_csrf_token()},
    )


@router.post("/auth/setup")
def auth_setup(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(default=""),
):
    """Handle account creation form submission."""
    if user_exists():
        return RedirectResponse(url="/login", status_code=303)

    if not _validate_csrf_token(csrf_token):
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": "Invalid or expired form token. Please try again.", "csrf_token": _generate_csrf_token()},
            status_code=403,
        )

    # Validation
    error = None
    if not username.strip():
        error = "Username is required"
    elif len(password) < 8:
        error = "Password must be at least 8 characters"
    elif password != confirm_password:
        error = "Passwords do not match"

    if error:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"error": error, "csrf_token": _generate_csrf_token()},
            status_code=400,
        )

    user_id = create_user(username.strip(), password)
    session_id = create_session(user_id)
    response = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(response, session_id)
    return response


@router.post("/auth/logout")
def auth_logout(request: Request):
    """Handle logout — delete session and clear cookie."""
    cookie_value = request.cookies.get("backlogia_session")
    if cookie_value:
        try:
            signer = _get_signer()
            session_id = signer.loads(cookie_value)
            delete_session(session_id)
        except Exception:
            pass

    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("backlogia_session")
    return response
