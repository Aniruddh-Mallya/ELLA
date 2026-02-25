"""
inbound_adapters.py - Cloud-Ready (v3: User Lifecycle)
=====================================================
CHANGES FROM v2:
  - get_user_service()  → new factory injecting UserRepositoryPort + PasswordHasherPort
  - GET /api/users      → admin lists all users
  - POST /api/users     → admin creates a user
  - PATCH /api/users/role → admin changes a user's role
  - DELETE /api/users   → admin deletes a user
  - All existing routes UNCHANGED
"""
import os, sys
from fastapi import FastAPI, Header, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from domain import ResearchService, AuthService, UserService
from outbound_adapters import (
    SQLiteProjectAdapter, MockProjectAdapter, PostgresProjectAdapter,
    SQLiteUserAdapter, MockUserAdapter, PostgresUserAdapter,
    JWTAdapter, ScholarAdapter, LogBrokerAdapter,
    BcryptHasher, seed_users,
)

# -- Read config from environment (set by Terraform -> App Settings) --
DATABASE_URL    = os.getenv("DATABASE_URL", "sqlite:///./data/research.db")
JWT_SECRET      = os.getenv("JWT_SECRET", "rms_secret_2026")
DEFAULT_ADAPTER = os.getenv("DEFAULT_ADAPTER_MODE", "prod-sqlite")


# =====================================================================
# DEPENDENCY FACTORIES
# =====================================================================

def get_db_adapter(x_adapter_mode: str = Header(None)):
    """Project database adapter — unchanged logic, renamed classes."""
    mode = x_adapter_mode or DEFAULT_ADAPTER
    if mode == "dev-mock":
        return MockProjectAdapter()
    if mode == "prod-postgres":
        return PostgresProjectAdapter(DATABASE_URL)
    return SQLiteProjectAdapter()


def get_user_adapter(x_adapter_mode: str = Header(None)):
    """User repository adapter — mirrors get_db_adapter() exactly."""
    mode = x_adapter_mode or DEFAULT_ADAPTER
    if mode == "dev-mock":
        return MockUserAdapter()
    if mode == "prod-postgres":
        return PostgresUserAdapter(DATABASE_URL)
    return SQLiteUserAdapter()


def get_auth_service(user_repo=Depends(get_user_adapter)):
    """Auth service — now backed by a real user repository + bcrypt."""
    hasher = BcryptHasher()
    return AuthService(
        user_repo=user_repo,
        token_provider=JWTAdapter(secret=JWT_SECRET),
        hasher=hasher,
    )


def get_user_service(user_repo=Depends(get_user_adapter)):
    """User service — admin-only CRUD for user lifecycle."""
    return UserService(user_repo=user_repo, hasher=BcryptHasher())


def get_research_service(db=Depends(get_db_adapter)):
    return ResearchService(db, ScholarAdapter(), LogBrokerAdapter())


# =====================================================================
# HELPER: Extract user from Authorization header
# =====================================================================

def _extract_user(authorization: str, auth: AuthService):
    """Parse Bearer token and return User or raise 401."""
    from ports import User
    user = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        user = auth.authorize(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login.")
    return user


# =====================================================================
# APP SETUP + SEED
# =====================================================================

app = FastAPI(title="RMS Modular 4-Pillar System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup_seed():
    """Seed default users into whichever DB the default adapter points to."""
    hasher = BcryptHasher()
    try:
        if DEFAULT_ADAPTER == "prod-postgres":
            repo = PostgresUserAdapter(DATABASE_URL)
        else:
            repo = SQLiteUserAdapter()
        seed_users(repo, hasher)
    except Exception as e:
        print(f"[SEED] Warning: Could not seed users — {e}", file=sys.stderr)


# =====================================================================
# ROUTES — EXISTING (UNCHANGED)
# =====================================================================

@app.get("/")
async def serve_ui():
    return FileResponse("index.html")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "adapter": DEFAULT_ADAPTER}


@app.post("/api/login")
async def login(payload: dict = Body(...), auth: AuthService = Depends(get_auth_service)):
    """
    Requires {email, password}. Returns {token, role} on success, 401 on failure.
    """
    email = payload.get("email", "")
    password = payload.get("password", "")
    try:
        return auth.authenticate(email, password)
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/api/projects")
async def list_projects(service: ResearchService = Depends(get_research_service)):
    try:
        return [p.model_dump() for p in service.get_all_projects()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Adapter Connection Failed: {str(e)}")


@app.post("/api/projects")
async def create_project(
    data: dict,
    service: ResearchService = Depends(get_research_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Extracts user from JWT token."""
    from ports import Project, User

    user = _extract_user(authorization, auth)

    try:
        proj = Project(title=data["title"], researcher=data["researcher"])
        return service.create_project(proj, user).model_dump()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================================================================
# ROUTES — v3: USER LIFECYCLE (NEW)
# =====================================================================

@app.get("/api/users")
async def list_users(
    user_svc: UserService = Depends(get_user_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Admin-only: list all users (email + role, never password_hash)."""
    caller = _extract_user(authorization, auth)
    try:
        return user_svc.list_users(caller)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.post("/api/users")
async def create_user(
    payload: dict = Body(...),
    user_svc: UserService = Depends(get_user_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Admin-only: create a new user {email, password, role}."""
    caller = _extract_user(authorization, auth)
    try:
        return user_svc.create_user(
            email=payload.get("email", ""),
            password=payload.get("password", ""),
            role=payload.get("role", ""),
            caller=caller,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/api/users/role")
async def change_user_role(
    payload: dict = Body(...),
    user_svc: UserService = Depends(get_user_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Admin-only: change a user's role {email, role}."""
    caller = _extract_user(authorization, auth)
    try:
        return user_svc.change_role(
            email=payload.get("email", ""),
            new_role=payload.get("role", ""),
            caller=caller,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/users")
async def delete_user(
    payload: dict = Body(...),
    user_svc: UserService = Depends(get_user_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Admin-only: delete a user {email}."""
    caller = _extract_user(authorization, auth)
    try:
        return user_svc.delete_user(
            email=payload.get("email", ""),
            caller=caller,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================================================================
# DEBUG (UNCHANGED)
# =====================================================================

@app.get("/debug")
async def debug_info():
    """Debug endpoint for Azure troubleshooting."""
    import platform
    info = {
        "python_version": platform.python_version(),
        "default_adapter": DEFAULT_ADAPTER,
        "database_url_set": bool(os.getenv("DATABASE_URL")),
        "jwt_secret_set": bool(os.getenv("JWT_SECRET")),
    }
    if DEFAULT_ADAPTER == "prod-postgres" and os.getenv("DATABASE_URL"):
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(DATABASE_URL)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            info["postgres_connection"] = "connected OK"
        except Exception as e:
            info["postgres_connection"] = f"FAILED: {e}"
    return info
