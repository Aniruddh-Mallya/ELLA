import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from typing import List, Optional

from ports import Project, User
from domain import ResearchService, AuthService
from adapters import SQLiteAdapter, JWTAdapter

# --- 1. Initialization (Pluggable Components) ---
db_adapter = SQLiteAdapter()
jwt_adapter = JWTAdapter()

def get_auth_service() -> AuthService:
    return AuthService(jwt_adapter)

def get_research_service() -> ResearchService:
    return ResearchService(db_adapter)

# --- 2. Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles system startup and shutdown. Performs diagnostic checks on startup.
    """
    print("--- RMS SYSTEM BOOTING ---")
    try:
        # Diagnostic check of the Data Mapper (Power Brick)
        projects = db_adapter.fetch_all()
        print(f"[DIAGNOSTIC] Data volume check: OK ({len(projects)} records found)")
    except Exception as e:
        print(f"[DIAGNOSTIC] CRITICAL: Unable to access database.")
        print(f"Details: {str(e)}")
        print("[DIAGNOSTIC] ACTION: Check if 'data' folder exists and is writable.")
    
    yield  # The app runs while this is held
    
    print("--- RMS SYSTEM SHUTTING DOWN ---")

# --- 3. App Setup ---
app = FastAPI(title="RMS Hexagonal API (Pure Domain)", lifespan=lifespan)

# --- 4. Dependency Injection Slots ---
def get_current_user(
    authorization: Optional[str] = Header(None),
    auth_service: AuthService = Depends(get_auth_service)
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    token = authorization.split(" ")[1]
    user = auth_service.authorize(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session Invalid")
    return user

# --- 5. Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 6. Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error loading index.html: {str(e)}"

@app.post("/api/login")
async def login(credentials: dict, auth_service: AuthService = Depends(get_auth_service)):
    email = credentials.get("email", "")
    return auth_service.authenticate(email)

@app.get("/api/projects", response_model=List[Project])
async def get_projects(
    user: User = Depends(get_current_user),
    research_service: ResearchService = Depends(get_research_service)
):
    return research_service.get_all_projects()

@app.post("/api/projects", response_model=Project)
async def add_project(
    project: Project, 
    user: User = Depends(get_current_user),
    research_service: ResearchService = Depends(get_research_service)
):
    try:
        return research_service.create_project(project, user)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        print(f"[SERVER-ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

# --- 7. Execution ---
if __name__ == "__main__":
    # Ensure uvicorn runs on 0.0.0.0 for Docker networking
    uvicorn.run(app, host="0.0.0.0", port=8000)