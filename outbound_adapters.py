import jwt
import json
import httpx
import datetime
from typing import List, Dict, Optional
from sqlalchemy import create_engine, Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import sessionmaker, declarative_base
from ports import (
    ProjectDatabasePort, TokenProviderPort, ResearchApiPort,
    UserRepositoryPort, AuthMethodPort,
    Project, Paper,
)

Base = declarative_base()


# ═══════════════════════════════════════════════════════════════════
# SQLAlchemy Models
# ═══════════════════════════════════════════════════════════════════

class DBProject(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    ref_id = Column(String, unique=True)
    title = Column(String)
    owner_email = Column(String)  # links the project to a real user (by email)


class DBSavedPaper(Base):
    """A paper snapshot saved against a project (closes the search→project loop)."""
    __tablename__ = "saved_papers"
    id = Column(Integer, primary_key=True)
    project_ref_id = Column(String, index=True, nullable=False)  # links to DBProject.ref_id
    paper_id = Column(String, nullable=False)                    # provider id (e.g. OpenAlex URL)
    title = Column(String)
    authors = Column(String)          # JSON-encoded list[str] (a column can't hold a list)
    year = Column(Integer, nullable=True)
    venue = Column(String, nullable=True)
    citation_count = Column(Integer, default=0)
    abstract = Column(String, nullable=True)
    url = Column(String, nullable=True)
    open_access_pdf = Column(String, nullable=True)
    source = Column(String, default="unknown")
    # the same paper can't be saved twice to the same project
    __table_args__ = (UniqueConstraint("project_ref_id", "paper_id", name="uq_project_paper"),)


def _row_to_paper(row: "DBSavedPaper") -> Paper:
    """Map a stored row back into our provider-agnostic Paper model."""
    try:
        authors = json.loads(row.authors) if row.authors else []
    except (ValueError, TypeError):
        authors = []
    return Paper(
        paper_id=row.paper_id,
        title=row.title or "(untitled)",
        authors=authors,
        year=row.year,
        venue=row.venue,
        citation_count=row.citation_count or 0,
        abstract=row.abstract,
        url=row.url,
        open_access_pdf=row.open_access_pdf,
        source=row.source or "unknown",
    )


def _new_saved_row(project_ref_id: str, paper: Paper) -> "DBSavedPaper":
    """Build a storable row from a Paper (snapshot of all display fields)."""
    return DBSavedPaper(
        project_ref_id=project_ref_id,
        paper_id=paper.paper_id,
        title=paper.title,
        authors=json.dumps(paper.authors or []),
        year=paper.year,
        venue=paper.venue,
        citation_count=paper.citation_count or 0,
        abstract=paper.abstract,
        url=paper.url,
        open_access_pdf=paper.open_access_pdf,
        source=paper.source,
    )


class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin" | "researcher"
    # --- researcher profile (all nullable; filled in by the user) ---
    full_name = Column(String, nullable=True)
    institution = Column(String, nullable=True)
    orcid_id = Column(String, nullable=True)


# ═══════════════════════════════════════════════════════════════════
# PILLAR 1: PERSISTENCE — Project Adapters (UNCHANGED logic)
# ═══════════════════════════════════════════════════════════════════

class SQLiteProjectAdapter(ProjectDatabasePort):
    """Renamed from SQLiteAdapter for clarity."""
    def __init__(self, db_url: str = "sqlite:///./data/research.db"):
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def save(self, project: Project) -> Project:
        with self.SessionLocal() as db:
            db_item = DBProject(ref_id=project.reference_id, title=project.title, owner_email=project.owner_email)
            db.add(db_item)
            db.commit()
            return project

    def fetch_all(self) -> List[Project]:
        with self.SessionLocal() as db:
            items = db.query(DBProject).all()
            return [Project(reference_id=i.ref_id, title=i.title, owner_email=i.owner_email or "") for i in items]

    def fetch_by_ref(self, reference_id: str) -> Optional[Project]:
        with self.SessionLocal() as db:
            i = db.query(DBProject).filter(DBProject.ref_id == reference_id).first()
            if i is None:
                return None
            return Project(reference_id=i.ref_id, title=i.title, owner_email=i.owner_email or "")

    def save_paper(self, project_ref_id: str, paper: Paper) -> Paper:
        with self.SessionLocal() as db:
            db.add(_new_saved_row(project_ref_id, paper))
            db.commit()
            return paper

    def fetch_papers(self, project_ref_id: str) -> List[Paper]:
        with self.SessionLocal() as db:
            rows = db.query(DBSavedPaper).filter(DBSavedPaper.project_ref_id == project_ref_id).all()
            return [_row_to_paper(r) for r in rows]

    def remove_paper(self, project_ref_id: str, paper_id: str) -> bool:
        with self.SessionLocal() as db:
            row = db.query(DBSavedPaper).filter(
                DBSavedPaper.project_ref_id == project_ref_id,
                DBSavedPaper.paper_id == paper_id,
            ).first()
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True


class PostgresProjectAdapter(ProjectDatabasePort):
    """Renamed from PostgresAdapter for clarity."""
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def save(self, project: Project) -> Project:
        with self.SessionLocal() as db:
            db_item = DBProject(ref_id=project.reference_id, title=project.title, owner_email=project.owner_email)
            db.add(db_item)
            db.commit()
            return project

    def fetch_all(self) -> List[Project]:
        with self.SessionLocal() as db:
            items = db.query(DBProject).all()
            return [Project(reference_id=i.ref_id, title=i.title, owner_email=i.owner_email or "") for i in items]

    def fetch_by_ref(self, reference_id: str) -> Optional[Project]:
        with self.SessionLocal() as db:
            i = db.query(DBProject).filter(DBProject.ref_id == reference_id).first()
            if i is None:
                return None
            return Project(reference_id=i.ref_id, title=i.title, owner_email=i.owner_email or "")

    def save_paper(self, project_ref_id: str, paper: Paper) -> Paper:
        with self.SessionLocal() as db:
            db.add(_new_saved_row(project_ref_id, paper))
            db.commit()
            return paper

    def fetch_papers(self, project_ref_id: str) -> List[Paper]:
        with self.SessionLocal() as db:
            rows = db.query(DBSavedPaper).filter(DBSavedPaper.project_ref_id == project_ref_id).all()
            return [_row_to_paper(r) for r in rows]

    def remove_paper(self, project_ref_id: str, paper_id: str) -> bool:
        with self.SessionLocal() as db:
            row = db.query(DBSavedPaper).filter(
                DBSavedPaper.project_ref_id == project_ref_id,
                DBSavedPaper.paper_id == paper_id,
            ).first()
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True


class MockProjectAdapter(ProjectDatabasePort):
    """Renamed from MockDBAdapter for clarity."""
    def __init__(self):
        self.projects = []
        self.papers: Dict[str, List[Paper]] = {}  # project_ref_id -> [Paper, ...]
    def save(self, p):
        self.projects.append(p)
        return p
    def fetch_all(self):
        return self.projects
    def fetch_by_ref(self, reference_id):
        return next((p for p in self.projects if p.reference_id == reference_id), None)
    def save_paper(self, project_ref_id, paper):
        self.papers.setdefault(project_ref_id, []).append(paper)
        return paper
    def fetch_papers(self, project_ref_id):
        return list(self.papers.get(project_ref_id, []))
    def remove_paper(self, project_ref_id, paper_id):
        items = self.papers.get(project_ref_id, [])
        for idx, p in enumerate(items):
            if p.paper_id == paper_id:
                items.pop(idx)
                return True
        return False


# ═══════════════════════════════════════════════════════════════════
# PILLAR 1b: PERSISTENCE — User Adapters (v3: +fetch_all, update_role, delete)
# ═══════════════════════════════════════════════════════════════════

class SQLiteUserAdapter(UserRepositoryPort):
    def __init__(self, db_url: str = "sqlite:///./data/research.db"):
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_by_email(self, email: str) -> Optional[Dict]:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return None
            return {"email": user.email, "role": user.role, "password_hash": user.password_hash}

    def save(self, email: str, password_hash: str, role: str) -> None:
        with self.SessionLocal() as db:
            existing = db.query(DBUser).filter(DBUser.email == email).first()
            if existing:
                return  # Already seeded — skip
            db.add(DBUser(email=email, password_hash=password_hash, role=role))
            db.commit()

    def fetch_all(self) -> List[Dict]:
        with self.SessionLocal() as db:
            users = db.query(DBUser).all()
            return [{"email": u.email, "role": u.role} for u in users]

    def update_role(self, email: str, new_role: str) -> bool:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return False
            user.role = new_role
            db.commit()
            return True

    def delete(self, email: str) -> bool:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return False
            db.delete(user)
            db.commit()
            return True

    def get_profile(self, email: str) -> Optional[Dict]:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return None
            return {
                "email": user.email, "role": user.role,
                "full_name": user.full_name, "institution": user.institution,
                "orcid_id": user.orcid_id,
            }

    def update_profile(self, email: str, full_name, institution, orcid_id) -> bool:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return False
            user.full_name = full_name
            user.institution = institution
            user.orcid_id = orcid_id
            db.commit()
            return True


class PostgresUserAdapter(UserRepositoryPort):
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_by_email(self, email: str) -> Optional[Dict]:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return None
            return {"email": user.email, "role": user.role, "password_hash": user.password_hash}

    def save(self, email: str, password_hash: str, role: str) -> None:
        with self.SessionLocal() as db:
            existing = db.query(DBUser).filter(DBUser.email == email).first()
            if existing:
                return
            db.add(DBUser(email=email, password_hash=password_hash, role=role))
            db.commit()

    def fetch_all(self) -> List[Dict]:
        with self.SessionLocal() as db:
            users = db.query(DBUser).all()
            return [{"email": u.email, "role": u.role} for u in users]

    def update_role(self, email: str, new_role: str) -> bool:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return False
            user.role = new_role
            db.commit()
            return True

    def delete(self, email: str) -> bool:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return False
            db.delete(user)
            db.commit()
            return True

    def get_profile(self, email: str) -> Optional[Dict]:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return None
            return {
                "email": user.email, "role": user.role,
                "full_name": user.full_name, "institution": user.institution,
                "orcid_id": user.orcid_id,
            }

    def update_profile(self, email: str, full_name, institution, orcid_id) -> bool:
        with self.SessionLocal() as db:
            user = db.query(DBUser).filter(DBUser.email == email).first()
            if user is None:
                return False
            user.full_name = full_name
            user.institution = institution
            user.orcid_id = orcid_id
            db.commit()
            return True


class MockUserAdapter(UserRepositoryPort):
    def __init__(self):
        self.users: Dict[str, Dict] = {}

    def get_by_email(self, email: str) -> Optional[Dict]:
        return self.users.get(email)

    def save(self, email: str, password_hash: str, role: str) -> None:
        self.users[email] = {
            "email": email, "role": role, "password_hash": password_hash,
            "full_name": None, "institution": None, "orcid_id": None,
        }

    def fetch_all(self) -> List[Dict]:
        return [{"email": u["email"], "role": u["role"]} for u in self.users.values()]

    def update_role(self, email: str, new_role: str) -> bool:
        if email not in self.users:
            return False
        self.users[email]["role"] = new_role
        return True

    def delete(self, email: str) -> bool:
        if email not in self.users:
            return False
        del self.users[email]
        return True

    def get_profile(self, email: str) -> Optional[Dict]:
        u = self.users.get(email)
        if u is None:
            return None
        return {k: u.get(k) for k in ("email", "role", "full_name", "institution", "orcid_id")}

    def update_profile(self, email: str, full_name, institution, orcid_id) -> bool:
        if email not in self.users:
            return False
        self.users[email].update(full_name=full_name, institution=institution, orcid_id=orcid_id)
        return True


# ═══════════════════════════════════════════════════════════════════
# PILLAR 2: IDENTITY — Token + Password Adapters
# ═══════════════════════════════════════════════════════════════════

class JWTAdapter(TokenProviderPort):
    def __init__(self, secret: str):
        self.secret = secret

    def encode(self, p):
        data = {**p, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)}
        return jwt.encode(data, self.secret, algorithm="HS256")

    def decode(self, t):
        try:
            return jwt.decode(t, self.secret, algorithms=["HS256"])
        except Exception:
            return None


class PasswordAuthAdapter(AuthMethodPort):
    """The 'password' login technique. Owns bcrypt internally — this is where the
    former PasswordHasherPort/BcryptHasher folded in.

    Two responsibilities, both genuinely belonging to passwords:
      - authenticate(): verify an email + password at login.
      - hash():         turn a new password into a stored hash (used when an admin
                        creates an account, and when seeding the default users).
    """
    name = "password"

    def __init__(self, user_repo: UserRepositoryPort):
        # Needs the user store to look up the stored hash during verification.
        self.user_repo = user_repo

    def hash(self, password: str) -> str:
        import bcrypt
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def _verify(self, password: str, hashed: str) -> bool:
        import bcrypt
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

    def authenticate(self, credentials: Dict) -> Optional[Dict]:
        """Verify {email, password}. Returns {email, role} on success, else None."""
        email = credentials.get("email", "")
        password = credentials.get("password", "")
        record = self.user_repo.get_by_email(email)
        if record is None:
            return None
        # An account created via OAuth (later) may have no password — reject here.
        stored = record.get("password_hash")
        if not stored:
            return None
        if not self._verify(password, stored):
            return None
        return {"email": record["email"], "role": record["role"]}


# ═══════════════════════════════════════════════════════════════════
# PILLAR 3: INTEGRATIONS — Research API Adapters
# ═══════════════════════════════════════════════════════════════════

class OpenAlexAdapter(ResearchApiPort):
    """Real adapter backed by the OpenAlex API (https://openalex.org).

    Free, no API key. Passing a contact email puts us in OpenAlex's
    faster "polite pool". We translate OpenAlex's raw JSON into our own
    provider-agnostic `Paper` model so nothing downstream is coupled to
    OpenAlex's response shape.
    """
    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, mailto: Optional[str] = None, timeout: float = 10.0):
        self.mailto = mailto
        self.timeout = timeout

    def search_papers(self, query: str, limit: int = 10) -> List[Paper]:
        params = {
            "search": query,
            "per-page": max(1, min(limit, 25)),
        }
        if self.mailto:
            params["mailto"] = self.mailto  # OpenAlex polite-pool hint

        headers = {"User-Agent": f"ELLA-RMS/1.0 (mailto:{self.mailto or 'unknown'})"}

        try:
            resp = httpx.get(self.BASE_URL, params=params, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as e:
            # Translate any transport/HTTP error into a domain-neutral error
            raise RuntimeError(f"OpenAlex request failed: {e}") from e

        return [self._to_paper(work) for work in payload.get("results", [])]

    # ---- mapping helpers (OpenAlex JSON -> our Paper) ----

    @staticmethod
    def _reconstruct_abstract(inverted_index: Optional[Dict]) -> Optional[str]:
        """OpenAlex ships abstracts as an inverted index {word: [positions]}.
        Rebuild the original sentence by placing each word at its position(s)."""
        if not inverted_index:
            return None
        slots = []
        for word, positions in inverted_index.items():
            for pos in positions:
                slots.append((pos, word))
        slots.sort(key=lambda pair: pair[0])
        return " ".join(word for _, word in slots) or None

    def _to_paper(self, work: Dict) -> Paper:
        authorships = work.get("authorships") or []
        authors = [
            (a.get("author") or {}).get("display_name")
            for a in authorships
            if (a.get("author") or {}).get("display_name")
        ]

        # venue lives under primary_location.source.display_name (nullable chain)
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        venue = source.get("display_name")

        open_access = work.get("open_access") or {}

        return Paper(
            paper_id=work.get("id") or "",
            title=work.get("title") or work.get("display_name") or "(untitled)",
            authors=authors,
            year=work.get("publication_year"),
            venue=venue,
            citation_count=work.get("cited_by_count") or 0,
            abstract=self._reconstruct_abstract(work.get("abstract_inverted_index")),
            url=work.get("doi") or work.get("id"),
            open_access_pdf=open_access.get("oa_url"),
            source="OpenAlex",
        )


class MockResearchApiAdapter(ResearchApiPort):
    """Offline stand-in used for tests and the `mock` provider mode.

    Returns deterministic fake `Paper` objects — no network calls — so the
    UI and tests work without hitting OpenAlex."""
    def search_papers(self, query: str, limit: int = 10) -> List[Paper]:
        return [
            Paper(
                paper_id=f"mock:{query}:{i}",
                title=f"A Study of {query} (part {i + 1})",
                authors=["Ada Lovelace", "Alan Turing"],
                year=2020 + i,
                venue="Journal of Mock Studies",
                citation_count=42 + i,
                abstract=f"This is a mock abstract about {query} for offline testing.",
                url="https://example.org/mock",
                open_access_pdf=None,
                source="Mock",
            )
            for i in range(min(limit, 3))
        ]


# ═══════════════════════════════════════════════════════════════════
# SEED: Insert default users on first run
# ═══════════════════════════════════════════════════════════════════

def seed_users(user_repo: UserRepositoryPort, password_method, users: List[Dict]) -> None:
    """
    Seeds the given users if they don't already exist.

    `password_method` is the password login technique (PasswordAuthAdapter); we use
    its hash() to scramble each seed password. Credentials are supplied by the caller
    (driven by environment variables in inbound_adapters.py) — no passwords are
    hardcoded here. Called once during app startup.
    """
    for u in users:
        user_repo.save(
            email=u["email"],
            password_hash=password_method.hash(u["password"]),
            role=u["role"],
        )
        # Only set default profile values if the user hasn't filled theirs in
        # yet — so a real edit survives a container restart / re-seed.
        existing = user_repo.get_profile(u["email"])
        if existing is not None and not existing.get("full_name"):
            user_repo.update_profile(
                email=u["email"],
                full_name=u.get("full_name"),
                institution=u.get("institution"),
                orcid_id=None,
            )
    if users:
        print(f"[SEED] Verified/created {len(users)} seed user(s).")
    else:
        print("[SEED] No seed users configured — set ADMIN_PASSWORD to create the admin account.")
