"""
inbound_adapters.py — Cloud-Ready (Student Edition) — FIXED
=============================================================
Fixes:
  1. PostgresAdapter is created LAZILY (not at import time)
     → app starts even if PostgreSQL is unreachable
  2. Added /debug endpoint to diagnose issues from the browser
  3. SQLite is the safe default — switch to Postgres via UI dropdown
"""
import os
from fastapi import FastAPI, Header, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from domain import ResearchService, AuthService
from outbound_adapters import SQLiteAdapter, MockDBAdapter, PostgresAdapter, JWTAdapter, ScholarAdapter, LogBrokerAdapter

# ── Read config from environment (set by Terraform → App Settings) ──
DATABASE_URL    = os.getenv("DATABASE_URL", "sqlite:///./data/research.db")
JWT_SECRET      = os.getenv("JWT_SECRET", "rms_secret_2026")
DEFAULT_ADAPTER = os.getenv("DEFAULT_ADAPTER_MODE", "prod-sqlite")

# --- DEPENDENCY FACTORY ---
def get_db_adapter(x_adapter_mode: str = Header(None)):
    mode = x_adapter_mode or DEFAULT_ADAPTER
    if mode == "dev-mock":
        return MockDBAdapter()
    if mode == "prod-postgres":
        try:
            return PostgresAdapter(DATABASE_URL)
        except Exception as e:
            # Don't crash the whole app — fall back to SQLite and report error
            print(f"[WARNING] PostgresAdapter failed: {e}. Falling back to SQLite.")
            raise HTTPException(
                status_code=503,
                detail=f"PostgreSQL connection failed: {str(e)}. Check DATABASE_URL and firewall rules."
            )
    return SQLiteAdapter()

def get_research_service(db=Depends(get_db_adapter)):
    return ResearchService(db, ScholarAdapter(), LogBrokerAdapter())

def get_auth_service():
    return AuthService(JWTAdapter(secret=JWT_SECRET))

# --- APP SETUP ---
app = FastAPI(title="RMS Modular 4-Pillar System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def serve_ui():
    return FileResponse("index.html")

@app.get("/health")
async def health_check():
    """Azure App Service pings this. Must return 200 quickly or you get 503."""
    return {"status": "healthy", "adapter": DEFAULT_ADAPTER}

@app.get("/debug")
async def debug_info():
    """
    Visit https://your-app.azurewebsites.net/debug in your browser
    to see what's going on inside the container.
    """
    import sys
    pg_status = "not tested"
    try:
        if "postgresql" in DATABASE_URL:
            from sqlalchemy import create_engine, text
            engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            pg_status = "connected OK"
    except Exception as e:
        pg_status = f"FAILED: {str(e)}"

    return {
        "python_version": sys.version,
        "DATABASE_URL_set": bool(os.getenv("DATABASE_URL")),
        "DATABASE_URL_prefix": DATABASE_URL[:30] + "..." if len(DATABASE_URL) > 30 else DATABASE_URL,
        "JWT_SECRET_set": bool(os.getenv("JWT_SECRET")),
        "DEFAULT_ADAPTER": DEFAULT_ADAPTER,
        "WEBSITES_PORT": os.getenv("WEBSITES_PORT", "not set"),
        "postgres_connection": pg_status,
    }

@app.post("/api/login")
async def login(payload: dict = Body(...), auth: AuthService = Depends(get_auth_service)):
    return auth.authenticate(payload.get("email"))

@app.get("/api/projects")
async def list_projects(service: ResearchService = Depends(get_research_service)):
    try:
        return [p.model_dump() for p in service.get_all_projects()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Adapter Connection Failed: {str(e)}")

@app.post("/api/projects")
async def create_project(data: dict, service: ResearchService = Depends(get_research_service)):
    from ports import Project, User
    try:
        proj = Project(title=data['title'], researcher=data['researcher'])
        user = User(email="admin@rms.com", role="admin")
        return service.create_project(proj, user).model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
