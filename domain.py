from typing import List, Dict, Optional
from ports import ResearchManagerPort, AuthPort, ProjectDatabasePort, TokenProviderPort, Project, User

class ResearchService(ResearchManagerPort):
    """The 'CPU' - Operates ONLY on Clean Domain Models."""
    def __init__(self, db_port: ProjectDatabasePort):
        self.db = db_port

    def get_all_projects(self) -> List[Project]:
        # Domain simply asks the Port for 'Projects'. 
        # It doesn't know there is a Mapper or SQL involved.
        return self.db.fetch_all()

    def create_project(self, project: Project, user: User) -> Project:
        if user.role not in ["admin", "researcher"]:
            raise PermissionError("Access Denied: Role unauthorized to create projects.")
        
        if len(project.title) < 4:
            raise ValueError("Validation Error: Project title is too short.")
            
        # The domain object already has its 'reference_id' generated at instantiation.
        # We just pass the clean object to the port.
        return self.db.save(project)

class AuthService(AuthPort):
    def __init__(self, token_provider: TokenProviderPort):
        self.token_provider = token_provider

    def authenticate(self, email: str) -> Dict:
        role = "admin" if "admin" in email.lower() else "researcher"
        token = self.token_provider.encode({"email": email, "role": role})
        return {"token": token, "role": role}

    def authorize(self, token: str) -> Optional[User]:
        payload = self.token_provider.decode(token)
        if payload: return User(email=payload['email'], role=payload['role'])
        return None