import re
from typing import List, Dict, Optional
from ports import (
    Project, ProjectView, User, Paper,
    ProjectDatabasePort, ResearchApiPort, MessageBrokerPort,
    TokenProviderPort, UserRepositoryPort, PasswordHasherPort,
)


class ResearchService:
    """The 'CPU' - Logic for research management.

    Now also enriches project listings with each owner's real profile,
    and stamps new projects with the authenticated creator as owner.
    """
    def __init__(self, db: ProjectDatabasePort, api: ResearchApiPort,
                 broker: MessageBrokerPort, user_repo: UserRepositoryPort):
        self.db = db
        self.api = api
        self.broker = broker
        self.user_repo = user_repo

    def get_all_projects(self) -> List[ProjectView]:
        """Return projects joined with the owner's name + institution.

        (Looks up each owner's profile; for a local app the per-project
        lookup is fine — a future optimization would batch these.)"""
        views: List[ProjectView] = []
        for p in self.db.fetch_all():
            profile = self.user_repo.get_profile(p.owner_email) if p.owner_email else None
            profile = profile or {}
            views.append(ProjectView(
                reference_id=p.reference_id,
                title=p.title,
                status=p.status,
                owner_email=p.owner_email,
                # fall back to the email if the owner hasn't set a name yet
                owner_name=profile.get("full_name") or p.owner_email or None,
                owner_institution=profile.get("institution"),
            ))
        return views

    def search_papers(self, query: str, limit: int = 10) -> List[Paper]:
        """Search external academic literature via the ResearchApiPort.

        Pure business rules live here (input validation + event emission);
        the actual HTTP call to whichever provider is delegated to the
        injected adapter, so the domain stays infrastructure-free.
        """
        cleaned = (query or "").strip()
        if len(cleaned) < 2:
            raise ValueError("Validation Error: Search query must be at least 2 characters.")
        if limit < 1 or limit > 25:
            raise ValueError("Validation Error: limit must be between 1 and 25.")

        results = self.api.search_papers(cleaned, limit=limit)
        self.broker.publish_event("PAPER_SEARCH", {"query": cleaned, "count": len(results)})
        return results

    def create_project(self, project: Project, user: User) -> Project:
        if user.role not in ["admin", "researcher"]:
            raise PermissionError("Access Denied: Role unauthorized.")
        if len(project.title) < 5:
            raise ValueError("Validation Error: Title must be at least 5 chars.")

        # The project always belongs to whoever is logged in creating it —
        # never a typed-in name.
        project.owner_email = user.email

        saved = self.db.save(project)
        self.broker.publish_event("PROJECT_CREATED", {
            "ref_id": saved.reference_id,
            "owner": saved.owner_email,
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


class ProfileService:
    """Self-service researcher profile management.

    Deliberately self-only: every method acts on the CALLER's own record.
    There is no path here to edit someone else's profile, so an admin can
    never edit a researcher's profile — only the researcher can.

    Dependency (a port — no infrastructure imports):
      - user_repo:  UserRepositoryPort  (SQLite/Postgres/Mock)
    """
    # ORCID looks like 0000-0002-1825-0097 (last char may be a checksum 'X')
    _ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dXx]")

    def __init__(self, user_repo: UserRepositoryPort):
        self.user_repo = user_repo

    def get_my_profile(self, caller: User) -> Dict:
        profile = self.user_repo.get_profile(caller.email)
        if profile is None:
            raise ValueError("Profile not found.")
        return profile

    def update_my_profile(self, caller: User, full_name: str,
                          institution: Optional[str], orcid_id: Optional[str]) -> Dict:
        # Full name is required; institution is optional.
        if not full_name or not full_name.strip():
            raise ValueError("Validation Error: Full name is required.")

        # ORCID is optional, but if present it must be well-formed.
        cleaned_orcid = (orcid_id or "").strip()
        if cleaned_orcid and not self._ORCID_RE.fullmatch(cleaned_orcid):
            raise ValueError("Validation Error: ORCID must look like 0000-0002-1825-0097.")

        ok = self.user_repo.update_profile(
            email=caller.email,
            full_name=full_name.strip(),
            institution=(institution or "").strip() or None,
            orcid_id=cleaned_orcid or None,
        )
        if not ok:
            raise ValueError("Profile not found.")
        return self.user_repo.get_profile(caller.email)
