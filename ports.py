import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

# --- Domain Models ---
class Project(BaseModel):
    reference_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    researcher: str
    status: str = "Active"

class User(BaseModel):
    email: str
    role: str

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
    def search_papers(self, query: str) -> List[Dict]: pass

class MessageBrokerPort(ABC):
    @abstractmethod
    def publish_event(self, event_type: str, data: Dict) -> None: pass
