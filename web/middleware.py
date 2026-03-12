# middleware.py
# Optional authentication middleware for Backlogia

from urllib.parse import quote

from itsdangerous import URLSafeSerializer, BadSignature
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

from .services.auth_service import validate_session, user_exists

# Paths that are always accessible (no auth required)
PUBLIC_PATHS = {"/login", "/setup", "/auth/login", "/auth/setup", "/auth/logout"}
PUBLIC_PREFIXES = ("/static/", "/api/import/")


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret_key: str):
        super().__init__(app)
        self.signer = URLSafeSerializer(secret_key, salt="backlogia-session")

    async def dispatch(self, request, call_next):
        path = request.url.path

        # Always allow CORS preflight requests and public paths
        if request.method == "OPTIONS":
            response = await call_next(request)
            return response

        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES) or path == "/sw.js":
            response = await call_next(request)
            return response

        # Try to validate session from cookie
        user = None
        cookie_value = request.cookies.get("backlogia_session")
        if cookie_value:
            try:
                session_id = self.signer.loads(cookie_value)
                user = validate_session(session_id)
            except BadSignature:
                pass

        # Attach user to request state
        request.state.user = user

        if user is not None:
            response = await call_next(request)
            return response

        # No valid session — check if any user exists
        if not user_exists():
            return RedirectResponse(url="/setup", status_code=303)

        # User exists but not logged in
        if path.startswith("/api/"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        # HTML routes — redirect to login
        next_url = quote(path, safe="")
        return RedirectResponse(url=f"/login?next={next_url}", status_code=303)
