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


class UserService:
    """
    The 'HR Department' - Logic for user lifecycle management.

    Separate from AuthService to avoid god-class anti-pattern.
    All operations require an admin caller.

    Dependencies (all ports — no infrastructure imports):
      - user_repo:  UserRepositoryPort  (SQLite/Postgres/Mock)
      - hasher:     PasswordHasherPort  (bcrypt)
    """
    def __init__(self, user_repo: UserRepositoryPort, hasher: PasswordHasherPort):
        self.user_repo = user_repo
        self.hasher = hasher

    def _require_admin(self, caller: User) -> None:
        if caller.role != "admin":
            raise PermissionError("Access Denied: Admin role required.")

    def list_users(self, caller: User) -> List[Dict]:
        """Return all users (email + role only, never password_hash)."""
        self._require_admin(caller)
        return self.user_repo.fetch_all()

    def create_user(self, email: str, password: str, role: str, caller: User) -> Dict:
        """Create a new user with bcrypt-hashed password."""
        self._require_admin(caller)

        if not email or "@" not in email:
            raise ValueError("Validation Error: Invalid email address.")
        if len(password) < 6:
            raise ValueError("Validation Error: Password must be at least 6 characters.")
        if role not in ["admin", "researcher"]:
            raise ValueError("Validation Error: Role must be 'admin' or 'researcher'.")

        # Check if user already exists
        existing = self.user_repo.get_by_email(email)
        if existing is not None:
            raise ValueError(f"Validation Error: User '{email}' already exists.")

        hashed = self.hasher.hash(password)
        self.user_repo.save(email=email, password_hash=hashed, role=role)
        return {"email": email, "role": role}

    def change_role(self, email: str, new_role: str, caller: User) -> Dict:
        """Change a user's role. Admin cannot change their own role."""
        self._require_admin(caller)

        if caller.email == email:
            raise PermissionError("Cannot change your own role.")
        if new_role not in ["admin", "researcher"]:
            raise ValueError("Validation Error: Role must be 'admin' or 'researcher'.")

        success = self.user_repo.update_role(email, new_role)
        if not success:
            raise ValueError(f"User '{email}' not found.")
        return {"email": email, "role": new_role}

    def delete_user(self, email: str, caller: User) -> Dict:
        """Delete a user. Admin cannot delete themselves."""
        self._require_admin(caller)

        if caller.email == email:
            raise PermissionError("Cannot delete your own account.")

        success = self.user_repo.delete(email)
        if not success:
            raise ValueError(f"User '{email}' not found.")
        return {"email": email, "deleted": True}
