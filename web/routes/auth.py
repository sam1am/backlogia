# routes/auth.py
# Epic, Amazon, and GOG authentication routes

import subprocess
from typing import Optional
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["Authentication"])

# Session storage for Amazon auth flow
_amazon_auth_sessions = {}


class EpicAuthRequest(BaseModel):
    code: str


class AmazonAuthCompleteRequest(BaseModel):
    code: str
    session_id: Optional[str] = None


class GogAuthRequest(BaseModel):
    code: str


@router.get("/api/epic/status")
def epic_auth_status():
    """Check Epic Games authentication status via Legendary."""
    # Import here to avoid circular imports
    from ..sources.epic import is_legendary_installed, check_authentication

    try:
        if not is_legendary_installed():
            return {
                "success": True,
                "installed": False,
                "authenticated": False,
                "message": "Legendary CLI is not installed"
            }

        is_auth, username, error = check_authentication()

        if error == "corrective_action":
            return {
                "success": True,
                "installed": True,
                "authenticated": False,
                "needs_reauth": True,
                "message": "Epic requires you to accept updated terms. Please re-authenticate."
            }

        return {
            "success": True,
            "installed": True,
            "authenticated": is_auth,
            "username": username,
            "message": f"Logged in as {username}" if is_auth else "Not authenticated"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/epic/auth")
def epic_authenticate(body: EpicAuthRequest):
    """Authenticate with Epic Games using an authorization code."""
    # Import here to avoid circular imports
    from ..sources.epic import is_legendary_installed, check_authentication

    try:
        if not is_legendary_installed():
            raise HTTPException(
                status_code=400,
                detail="Legendary CLI is not installed. Please install it first."
            )

        auth_code = body.code.strip()

        if not auth_code:
            raise HTTPException(status_code=400, detail="Authorization code is required")

        # Run legendary auth with the provided code
        result = subprocess.run(
            ["legendary", "auth", "--code", auth_code],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            # Verify authentication succeeded
            is_auth, username, _ = check_authentication()
            if is_auth:
                return {
                    "success": True,
                    "message": f"Successfully authenticated as {username}",
                    "username": username
                }
            else:
                raise HTTPException(
                    status_code=500,
                    detail="Authentication appeared to succeed but verification failed"
                )
        else:
            error_msg = result.stderr.strip() if result.stderr else "Authentication failed"
            raise HTTPException(status_code=400, detail=error_msg)

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Authentication timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/amazon/auth/start")
def amazon_auth_start():
    """Start Amazon OAuth flow via Nile - returns login URL."""
    try:
        from ..sources.amazon import is_nile_installed, start_auth, logout, check_auth_status
        import uuid

        if not is_nile_installed():
            raise HTTPException(status_code=500, detail="Nile is not installed")

        # Log out first if already authenticated (for re-authentication)
        status = check_auth_status()
        if status.get("authenticated"):
            logout()

        auth_data, error = start_auth()
        if error:
            raise HTTPException(status_code=500, detail=error)

        # Store auth credentials with a session ID
        session_id = str(uuid.uuid4())
        _amazon_auth_sessions[session_id] = auth_data

        # Clean up old sessions (keep only last 10)
        if len(_amazon_auth_sessions) > 10:
            oldest = list(_amazon_auth_sessions.keys())[:-10]
            for key in oldest:
                del _amazon_auth_sessions[key]

        return {
            "success": True,
            "login_url": auth_data.get("login_url"),
            "session_id": session_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/amazon/auth/complete")
def amazon_auth_complete(body: AmazonAuthCompleteRequest):
    """Complete Amazon OAuth flow - register with auth code."""
    try:
        from ..sources.amazon import complete_auth

        code = body.code.strip()
        session_id = body.session_id.strip() if body.session_id else ""

        if not code:
            raise HTTPException(status_code=400, detail="Authorization code is required")

        # Extract code from URL if full URL was pasted
        if "openid.oa2.authorization_code=" in code:
            parsed = urlparse(code)
            params = parse_qs(parsed.query)
            code = params.get("openid.oa2.authorization_code", [code])[0]

        # Get stored auth credentials
        auth_data = _amazon_auth_sessions.pop(session_id, {}) if session_id else {}

        success, message = complete_auth(
            code,
            client_id=auth_data.get("client_id"),
            code_verifier=auth_data.get("code_verifier"),
            serial=auth_data.get("serial"),
        )

        if success:
            return {"success": True, "message": message}
        else:
            raise HTTPException(status_code=400, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/amazon/auth/status")
def amazon_auth_status():
    """Check Amazon authentication status via Nile."""
    try:
        from ..sources.amazon import is_nile_installed, check_auth_status

        if not is_nile_installed():
            return {
                "authenticated": False,
                "nile_installed": False,
                "error": "Nile is not installed"
            }

        status = check_auth_status()
        return {
            "authenticated": status.get("authenticated", False),
            "nile_installed": True,
            "username": status.get("username"),
            "error": status.get("error"),
        }

    except Exception as e:
        return {"authenticated": False, "error": str(e)}


@router.get("/api/gog/status")
def gog_auth_status():
    """Check GOG authentication status."""
    try:
        from ..sources.gog import check_auth_status, GOG_LOGIN_URL

        status = check_auth_status()
        return {
            "authenticated": status["authenticated"],
            "source": status.get("source"),
            "heroic": status.get("heroic", False),
            "login_url": GOG_LOGIN_URL,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/gog/auth")
def gog_authenticate(body: GogAuthRequest):
    """Exchange a GOG authorization code for stored access/refresh tokens."""
    try:
        from ..sources.gog import exchange_code_for_token, save_gog_token

        code = body.code.strip()
        if not code:
            raise HTTPException(status_code=400, detail="Authorization code is required")

        # Strip the full redirect URL down to just the code if the user pasted the URL
        if "code=" in code:
            parsed = urlparse(code)
            params = parse_qs(parsed.query)
            code = params.get("code", [code])[0]

        token_data = exchange_code_for_token(code)
        if not token_data or not token_data.get("access_token"):
            raise HTTPException(
                status_code=400,
                detail="Failed to exchange code for token. The code may be expired or invalid."
            )

        save_gog_token(token_data)
        return {"success": True, "message": "GOG authentication successful"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/gog/logout")
def gog_logout():
    """Clear stored GOG tokens."""
    try:
        from ..sources.gog import clear_gog_token
        clear_gog_token()
        return {"success": True, "message": "GOG credentials cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
