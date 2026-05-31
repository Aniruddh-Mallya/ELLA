import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

# --- Domain Models ---
class Project(BaseModel):
    reference_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    owner_email: str = ""   # set by the service from the authenticated creator
    status: str = "Active"

class ProjectView(BaseModel):
    """A project enriched with its owner's human details, for display.

    Returned by listing endpoints so the frontend shows a real name +
    institution instead of an email or a typed-in string.
    """
    reference_id: str
    title: str
    status: str = "Active"
    owner_email: str
    owner_name: Optional[str] = None
    owner_institution: Optional[str] = None

class User(BaseModel):
    email: str
    role: str

class Paper(BaseModel):
    """A normalized academic paper — provider-agnostic.

    Every research-API adapter (OpenAlex, Semantic Scholar, mock, ...)
    maps its own raw response shape into THIS model, so the domain and
    the frontend never have to know which provider answered.
    """
    paper_id: str
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    citation_count: int = 0
    abstract: Optional[str] = None
    url: Optional[str] = None
    open_access_pdf: Optional[str] = None
    source: str = "unknown"

# --- The 4+1 Outbound Ports (The Sockets) ---

class ProjectDatabasePort(ABC):
    @abstractmethod
    def save(self, project: Project) -> Project: pass
    @abstractmethod
    def fetch_all(self) -> List[Project]: pass

    # --- single-project lookup (needed to resolve ownership) ---
    @abstractmethod
    def fetch_by_ref(self, reference_id: str) -> Optional[Project]: pass
    # Returns the project with this reference_id, or None if not found.

    # --- saved papers (a project's collected literature) ---
    @abstractmethod
    def save_paper(self, project_ref_id: str, paper: "Paper") -> "Paper": pass
    # Stores a full snapshot of the paper against the project.

    @abstractmethod
    def fetch_papers(self, project_ref_id: str) -> List["Paper"]: pass
    # Returns every paper snapshot saved to this project.

    @abstractmethod
    def remove_paper(self, project_ref_id: str, paper_id: str) -> bool: pass
    # Returns True if a matching paper was found and removed, False otherwise.

class UserRepositoryPort(ABC):
    """Port for user persistence — mirrors ProjectDatabasePort symmetry."""
    @abstractmethod
    def get_by_email(self, email: str) -> Optional[Dict]: pass
    # Returns dict with keys: email, role, password_hash
    # (Dict instead of User to keep password_hash out of the domain model)

    @abstractmethod
    def save(self, email: str, password_hash: str, role: str) -> None: pass

    @abstractmethod
    def fetch_all(self) -> List[Dict]: pass
    # Returns list of dicts with keys: email, role (NO password_hash)

    @abstractmethod
    def update_role(self, email: str, new_role: str) -> bool: pass
    # Returns True if user was found and updated, False otherwise

    @abstractmethod
    def delete(self, email: str) -> bool: pass
    # Returns True if user was found and deleted, False otherwise

    @abstractmethod
    def get_profile(self, email: str) -> Optional[Dict]: pass
    # Returns dict with keys: email, role, full_name, institution, orcid_id
    # (NO password_hash — this is the safe-to-display profile)

    @abstractmethod
    def update_profile(self, email: str, full_name: Optional[str],
                       institution: Optional[str], orcid_id: Optional[str]) -> bool: pass
    # Returns True if user was found and updated, False otherwise

class TokenProviderPort(ABC):
    @abstractmethod
    def encode(self, payload: Dict) -> str: pass
    @abstractmethod
    def decode(self, token: str) -> Optional[Dict]: pass

class AuthMethodPort(ABC):
    """A single technique for proving identity at login — the unified 'ID-check slot'.

    Every login method plugs in here and does the same job: take whatever the
    visitor presents and return a VERIFIED identity, or None if the proof fails.
    Password is the only technique today; Google/GitHub will be added later as
    more adapters behind this same port. The shared 'issue a JWT' step lives in
    AuthService, so all methods converge on one consistent outcome.
    """
    # Short technique id set by each adapter, e.g. "password" | "google" | "github".
    name: str

    @abstractmethod
    def authenticate(self, credentials: Dict) -> Optional[Dict]:
        """Verify the presented credentials.

        Returns a verified identity {"email": str, "role": str} on success,
        or None if the proof is invalid.
        """
        pass

class ResearchApiPort(ABC):
    @abstractmethod
    def search_papers(self, query: str, limit: int = 10) -> List["Paper"]: pass
