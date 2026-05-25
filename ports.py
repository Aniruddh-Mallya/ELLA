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

class PasswordHasherPort(ABC):
    """Port for password hashing — keeps bcrypt out of domain."""
    @abstractmethod
    def hash(self, password: str) -> str: pass
    @abstractmethod
    def verify(self, password: str, hashed: str) -> bool: pass

class ResearchApiPort(ABC):
    @abstractmethod
    def search_papers(self, query: str, limit: int = 10) -> List["Paper"]: pass

class MessageBrokerPort(ABC):
    @abstractmethod
    def publish_event(self, event_type: str, data: Dict) -> None: pass
