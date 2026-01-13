import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

# --- Domain Models ---
class Project(BaseModel):
    # Pure Domain Identity (UUID). 
    # We ignore the database's auto-incrementing integer IDs.
    reference_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    researcher: str
    status: str = "Active"

class User(BaseModel):
    email: str
    role: str

# --- Inbound Ports ---
class ResearchManagerPort(ABC):
    @abstractmethod
    def get_all_projects(self) -> List[Project]:
        pass

    @abstractmethod
    def create_project(self, project: Project, user: User) -> Project:
        pass

class AuthPort(ABC):
    @abstractmethod
    def authenticate(self, email: str) -> Dict:
        pass

    @abstractmethod
    def authorize(self, token: str) -> Optional[User]:
        pass

# --- Outbound Ports ---
class ProjectDatabasePort(ABC):
    @abstractmethod
    def save(self, project: Project) -> Project:
        pass

    @abstractmethod
    def fetch_all(self) -> List[Project]:
        pass

class TokenProviderPort(ABC):
    @abstractmethod
    def encode(self, payload: Dict) -> str:
        pass

    @abstractmethod
    def decode(self, token: str) -> Optional[Dict]:
        pass