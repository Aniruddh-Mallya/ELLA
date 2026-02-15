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

# --- The 4 Outbound Ports (The Sockets) ---
class ProjectDatabasePort(ABC):
    @abstractmethod
    def save(self, project: Project) -> Project: pass
    @abstractmethod
    def fetch_all(self) -> List[Project]: pass

class TokenProviderPort(ABC):
    @abstractmethod
    def encode(self, payload: Dict) -> str: pass
    @abstractmethod
    def decode(self, token: str) -> Optional[Dict]: pass

class ResearchApiPort(ABC):
    @abstractmethod
    def search_papers(self, query: str) -> List[Dict]: pass

class MessageBrokerPort(ABC):
    @abstractmethod
    def publish_event(self, event_type: str, data: Dict) -> None: pass