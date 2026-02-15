from typing import List, Dict, Optional
from ports import Project, User, ProjectDatabasePort, ResearchApiPort, MessageBrokerPort, TokenProviderPort

class ResearchService:
    """The 'CPU' - Logic for research management."""
    def __init__(self, db: ProjectDatabasePort, api: ResearchApiPort, broker: MessageBrokerPort):
        self.db = db
        self.api = api
        self.broker = broker

    def get_all_projects(self) -> List[Project]:
        return self.db.fetch_all()

    def create_project(self, project: Project, user: User) -> Project:
        if user.role not in ["admin", "researcher"]:
            raise PermissionError("Access Denied: Role unauthorized.")
        if len(project.title) < 5:
            raise ValueError("Validation Error: Title must be at least 5 chars.")
        
        saved = self.db.save(project)
        self.broker.publish_event("PROJECT_CREATED", {
            "ref_id": saved.reference_id,
            "researcher": saved.researcher
        })
        return saved

class AuthService:
    """The 'Security Controller' - Logic for identity."""
    def __init__(self, token_provider: TokenProviderPort):
        self.token_provider = token_provider

    def authenticate(self, email: str) -> Dict:
        role = "admin" if "admin" in email.lower() else "researcher"
        token = self.token_provider.encode({"email": email, "role": role})
        return {"token": token, "role": role}

    def authorize(self, token: str) -> Optional[User]:
        payload = self.token_provider.decode(token)
        return User(email=payload['email'], role=payload['role']) if payload else None