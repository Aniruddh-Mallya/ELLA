"""
inbound_adapters.py - Cloud-Ready (Auth Upgrade v2)
=====================================================
CHANGES FROM v1:
  - get_user_adapter()  → mirrors get_db_adapter() symmetry
  - get_auth_service()  → now injects UserRepositoryPort + PasswordHasherPort
  - /api/login          → accepts {email, password} instead of just {email}
  - /api/projects POST  → extracts user from JWT token (no more hardcoded admin)
  - /debug              → shows adapter mode + postgres connectivity
  - seed_users()        → called once at startup to insert default users
"""
import os, sys
from fastapi import FastAPI, Header, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from domain import ResearchService, AuthService
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


def get_research_service(db=Depends(get_db_adapter)):
    return ResearchService(db, ScholarAdapter(), LogBrokerAdapter())


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
# ROUTES
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
    CHANGED: Now requires {email, password} instead of just {email}.
    Returns {token, role} on success, 401 on failure.
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
    """
    CHANGED: Extracts user from JWT token instead of hardcoding admin.
    The frontend sends 'Authorization: Bearer <token>' on every request.
    """
    from ports import Project, User

    # Extract user from token
    user = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        user = auth.authorize(token)

    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login.")

    try:
        proj = Project(title=data["title"], researcher=data["researcher"])
        return service.create_project(proj, user).model_dump()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


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
