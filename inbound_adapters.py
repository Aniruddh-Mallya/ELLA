"""
inbound_adapters.py - Cloud-Ready (v3: User Lifecycle)
=====================================================
CHANGES FROM v2:
  - get_user_service()  → new factory injecting UserRepositoryPort + the password technique
  - GET /api/users      → admin lists all users
  - POST /api/users     → admin creates a user
  - PATCH /api/users/role → admin changes a user's role
  - DELETE /api/users   → admin deletes a user
  - All existing routes UNCHANGED
"""
import os, sys, secrets
from fastapi import FastAPI, Header, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from domain import ResearchService, AuthService, UserService, ProfileService
from outbound_adapters import (
    SQLiteProjectAdapter, MockProjectAdapter, PostgresProjectAdapter,
    SQLiteUserAdapter, MockUserAdapter, PostgresUserAdapter,
    JWTAdapter, OpenAlexAdapter, MockResearchApiAdapter,
    PasswordAuthAdapter, seed_users,
)

# -- Read config from environment (see docker-compose.yml) --
DATABASE_URL       = os.getenv("DATABASE_URL", "sqlite:///./data/research.db")
DEFAULT_ADAPTER    = os.getenv("DEFAULT_ADAPTER_MODE", "prod-sqlite")
RESEARCH_API_MODE  = os.getenv("RESEARCH_API_MODE", "openalex")  # "openalex" | "mock"
OPENALEX_EMAIL     = os.getenv("OPENALEX_EMAIL", "")             # optional polite-pool contact

# JWT signing key. In production this MUST be provided via JWT_SECRET. If it is
# missing we generate a random key at startup rather than fall back to a known
# hardcoded one — a publicly-known key would let anyone forge an admin token.
# Trade-off: tokens issued before a restart stop working after it.
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    JWT_SECRET = secrets.token_urlsafe(32)
    print(
        "[AUTH] JWT_SECRET not set — generated a temporary key. "
        "Logins will not survive a restart. Set JWT_SECRET for stable sessions.",
        file=sys.stderr,
    )

# Seed credentials — supplied via environment, never hardcoded. An account is
# only created when its password is provided.
ADMIN_EMAIL         = os.getenv("ADMIN_EMAIL", "admin@rms.com")
ADMIN_PASSWORD      = os.getenv("ADMIN_PASSWORD")
RESEARCHER_EMAIL    = os.getenv("RESEARCHER_EMAIL", "researcher@rms.com")
RESEARCHER_PASSWORD = os.getenv("RESEARCHER_PASSWORD")


# =====================================================================
# DEPENDENCY FACTORIES
# =====================================================================

def get_db_adapter():
    """Project database adapter — chosen by the operator via DEFAULT_ADAPTER_MODE,
    never by the client. Swapping backends is a deployment decision, not a
    per-request one."""
    if DEFAULT_ADAPTER == "dev-mock":
        return MockProjectAdapter()
    if DEFAULT_ADAPTER == "prod-postgres":
        return PostgresProjectAdapter(DATABASE_URL)
    return SQLiteProjectAdapter()


def get_user_adapter():
    """User repository adapter — mirrors get_db_adapter() exactly."""
    if DEFAULT_ADAPTER == "dev-mock":
        return MockUserAdapter()
    if DEFAULT_ADAPTER == "prod-postgres":
        return PostgresUserAdapter(DATABASE_URL)
    return SQLiteUserAdapter()


def get_auth_service(user_repo=Depends(get_user_adapter)):
    """Auth service — verifies through the unified AuthMethodPort.

    Only the password technique is enabled today. Google/GitHub (Task 3) will be
    added as more entries in this `methods` map without touching AuthService.
    """
    methods = {"password": PasswordAuthAdapter(user_repo)}
    return AuthService(
        token_provider=JWTAdapter(secret=JWT_SECRET),
        methods=methods,
    )


def get_user_service(user_repo=Depends(get_user_adapter)):
    """User service — admin-only CRUD for user lifecycle."""
    return UserService(user_repo=user_repo, password=PasswordAuthAdapter(user_repo))


def get_profile_service(user_repo=Depends(get_user_adapter)):
    """Profile service — self-service; a user edits only their own profile."""
    return ProfileService(user_repo=user_repo)


def get_research_api_adapter(x_research_api: str = Header(None)):
    """Research-literature adapter — swappable provider.

    Defaults to OpenAlex; send `X-Research-Api: mock` (or set
    RESEARCH_API_MODE=mock) to use the offline stub. This is the exact
    same plug-and-play pattern as the database adapters.
    """
    mode = x_research_api or RESEARCH_API_MODE
    if mode == "mock":
        return MockResearchApiAdapter()
    return OpenAlexAdapter(mailto=OPENALEX_EMAIL or None)


def get_research_service(
    db=Depends(get_db_adapter),
    api=Depends(get_research_api_adapter),
    user_repo=Depends(get_user_adapter),
):
    # user_repo lets the service enrich project listings with owner profiles
    return ResearchService(db, api, user_repo)


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
    """Seed default users into every real backing store we can reach.

    Both SQLite and Postgres are seeded so the UI's adapter dropdown
    can flip between them without "user not found" errors. Failures
    in one backend don't block the other.
    """
    seed_list = []
    if ADMIN_PASSWORD:
        seed_list.append({
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "role": "admin",
            "full_name": "System Administrator", "institution": None,
        })
    if RESEARCHER_PASSWORD:
        seed_list.append({
            "email": RESEARCHER_EMAIL, "password": RESEARCHER_PASSWORD, "role": "researcher",
            "full_name": "Default Researcher", "institution": "ELLA Research Institute",
        })

    try:
        repo = SQLiteUserAdapter()
        seed_users(repo, PasswordAuthAdapter(repo), seed_list)
    except Exception as e:
        print(f"[SEED] SQLite seed skipped — {e}", file=sys.stderr)
    if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
        try:
            repo = PostgresUserAdapter(DATABASE_URL)
            seed_users(repo, PasswordAuthAdapter(repo), seed_list)
        except Exception as e:
            print(f"[SEED] Postgres seed skipped — {e}", file=sys.stderr)


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
        return auth.authenticate("password", {"email": email, "password": password})
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
    """Create a project owned by the authenticated caller.

    The owner is taken from the JWT — there is no researcher-name input.
    """
    from ports import Project

    user = _extract_user(authorization, auth)

    try:
        proj = Project(title=data["title"])  # owner is set by the service
        return service.create_project(proj, user).model_dump()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================================================================
# ROUTES — SAVED PAPERS (a project's collected literature)
# =====================================================================

@app.post("/api/projects/{ref_id}/papers")
async def save_paper_to_project(
    ref_id: str,
    data: dict = Body(...),
    service: ResearchService = Depends(get_research_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Save a searched paper to a project. Owner-only (enforced in the domain)."""
    from ports import Paper

    user = _extract_user(authorization, auth)
    try:
        paper = Paper(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid paper payload: {e}")

    try:
        return service.save_paper_to_project(ref_id, paper, user).model_dump()
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/projects/{ref_id}/papers")
async def list_project_papers(
    ref_id: str,
    service: ResearchService = Depends(get_research_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """List a project's saved papers. Any logged-in user may view (read-only)."""
    _extract_user(authorization, auth)
    try:
        return [p.model_dump() for p in service.get_project_papers(ref_id)]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/projects/{ref_id}/papers")
async def remove_project_paper(
    ref_id: str,
    paper_id: str,  # query param — OpenAlex ids are URLs, so not a path segment
    service: ResearchService = Depends(get_research_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Remove a saved paper from a project. Owner-only (enforced in the domain)."""
    user = _extract_user(authorization, auth)
    try:
        service.remove_paper_from_project(ref_id, paper_id, user)
        return {"removed": True, "paper_id": paper_id}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =====================================================================
# ROUTES — PROFILE (self-service; a user manages only their own)
# =====================================================================

@app.get("/api/profile")
async def get_profile(
    profile_svc: ProfileService = Depends(get_profile_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Return the logged-in user's own profile."""
    user = _extract_user(authorization, auth)
    try:
        return profile_svc.get_my_profile(user)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.put("/api/profile")
async def update_profile(
    payload: dict = Body(...),
    profile_svc: ProfileService = Depends(get_profile_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Update the logged-in user's OWN profile {full_name, institution, orcid_id}.

    Keyed entirely off the JWT, so it can only ever touch the caller's
    own record — admins cannot edit anyone else's profile.
    """
    user = _extract_user(authorization, auth)
    try:
        return profile_svc.update_my_profile(
            caller=user,
            full_name=payload.get("full_name", ""),
            institution=payload.get("institution", ""),
            orcid_id=payload.get("orcid_id", ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================================================================
# ROUTES — PAPER SEARCH (Pillar 3: external research literature)
# =====================================================================

@app.get("/api/papers/search")
def search_papers(
    q: str,
    limit: int = 10,
    service: ResearchService = Depends(get_research_service),
    auth: AuthService = Depends(get_auth_service),
    authorization: str = Header(None),
):
    """Search academic papers via the active research provider (OpenAlex).

    Defined as a SYNC `def` on purpose: the underlying HTTP call to
    OpenAlex is blocking, so FastAPI runs this handler in a worker thread
    and the main async event loop stays free to serve other requests.
    """
    _extract_user(authorization, auth)  # any logged-in user may search
    try:
        results = service.search_papers(q, limit=limit)
        return [p.model_dump() for p in results]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # Upstream provider failed (network, 429, 5xx, bad JSON)
        raise HTTPException(status_code=502, detail=str(e))


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
