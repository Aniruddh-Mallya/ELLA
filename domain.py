from typing import List, Dict, Optional
from ports import (
    Project, User,
    ProjectDatabasePort, ResearchApiPort, MessageBrokerPort,
    TokenProviderPort, UserRepositoryPort, PasswordHasherPort,
)


class ResearchService:
    """The 'CPU' - Logic for research management. (UNCHANGED)"""
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
            "researcher": saved.researcher,
        })
        return saved


class AuthService:
    """
    The 'Security Controller' - Logic for identity.

    CHANGED: Now authenticates against a user repository with hashed passwords,
    instead of deriving role from the email string.

    Dependencies (all ports — no infrastructure imports):
      - user_repo:       UserRepositoryPort   (SQLite/Postgres/Mock)
      - token_provider:  TokenProviderPort     (JWT)
      - hasher:          PasswordHasherPort    (bcrypt)
    """
    def __init__(
        self,
        user_repo: UserRepositoryPort,
        token_provider: TokenProviderPort,
        hasher: PasswordHasherPort,
    ):
        self.user_repo = user_repo
        self.token_provider = token_provider
        self.hasher = hasher

    def authenticate(self, email: str, password: str) -> Dict:
        """Validate credentials and return a JWT + role."""
        record = self.user_repo.get_by_email(email)
        if record is None:
            raise PermissionError("Invalid credentials.")

        if not self.hasher.verify(password, record["password_hash"]):
            raise PermissionError("Invalid credentials.")

        token = self.token_provider.encode({"email": record["email"], "role": record["role"]})
        return {"token": token, "role": record["role"]}

    def authorize(self, token: str) -> Optional[User]:
        """Decode a JWT and return the User, or None."""
        payload = self.token_provider.decode(token)
        return User(email=payload["email"], role=payload["role"]) if payload else None
