import jwt
import datetime
from typing import List, Dict, Optional
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base
from ports import (
    ProjectDatabasePort, TokenProviderPort, ResearchApiPort,
    MessageBrokerPort, UserRepositoryPort, PasswordHasherPort,
    Project,
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
    researcher = Column(String)


class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin" | "researcher"


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
            db_item = DBProject(ref_id=project.reference_id, title=project.title, researcher=project.researcher)
            db.add(db_item)
            db.commit()
            return project

    def fetch_all(self) -> List[Project]:
        with self.SessionLocal() as db:
            items = db.query(DBProject).all()
            return [Project(reference_id=i.ref_id, title=i.title, researcher=i.researcher) for i in items]


class PostgresProjectAdapter(ProjectDatabasePort):
    """Renamed from PostgresAdapter for clarity."""
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def save(self, project: Project) -> Project:
        with self.SessionLocal() as db:
            db_item = DBProject(ref_id=project.reference_id, title=project.title, researcher=project.researcher)
            db.add(db_item)
            db.commit()
            return project

    def fetch_all(self) -> List[Project]:
        with self.SessionLocal() as db:
            items = db.query(DBProject).all()
            return [Project(reference_id=i.ref_id, title=i.title, researcher=i.researcher) for i in items]


class MockProjectAdapter(ProjectDatabasePort):
    """Renamed from MockDBAdapter for clarity."""
    def __init__(self):
        self.projects = []
    def save(self, p):
        self.projects.append(p)
        return p
    def fetch_all(self):
        return self.projects


# ═══════════════════════════════════════════════════════════════════
# PILLAR 1b: PERSISTENCE — User Adapters (NEW)
#
# Symmetry:
#   ResearchService → ProjectDatabasePort → SQLite/Postgres ProjectAdapter
#   AuthService     → UserRepositoryPort  → SQLite/Postgres UserAdapter
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


class MockUserAdapter(UserRepositoryPort):
    def __init__(self):
        self.users: Dict[str, Dict] = {}

    def get_by_email(self, email: str) -> Optional[Dict]:
        return self.users.get(email)

    def save(self, email: str, password_hash: str, role: str) -> None:
        self.users[email] = {"email": email, "role": role, "password_hash": password_hash}


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


class BcryptHasher(PasswordHasherPort):
    """Adapter that wraps bcrypt — keeps the library out of domain.py."""
    def hash(self, password: str) -> str:
        import bcrypt
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify(self, password: str, hashed: str) -> bool:
        import bcrypt
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ═══════════════════════════════════════════════════════════════════
# PILLAR 3: INTEGRATIONS (UNCHANGED)
# ═══════════════════════════════════════════════════════════════════

class ScholarAdapter(ResearchApiPort):
    def search_papers(self, q):
        return [{"source": "Scholar", "title": f"Study of {q}"}]


# ═══════════════════════════════════════════════════════════════════
# PILLAR 4: MESSAGING (UNCHANGED)
# ═══════════════════════════════════════════════════════════════════

class LogBrokerAdapter(MessageBrokerPort):
    def publish_event(self, t, d):
        print(f"[EVENT-BROKER] Broadcast: {t} | Data: {d}")


# ═══════════════════════════════════════════════════════════════════
# SEED: Insert default users on first run
# ═══════════════════════════════════════════════════════════════════

def seed_users(user_repo: UserRepositoryPort, hasher: PasswordHasherPort) -> None:
    """
    Seeds two default users if they don't already exist.
    Called once during app startup from inbound_adapters.py.
    """
    defaults = [
        {"email": "admin@rms.com",      "password": "admin123",      "role": "admin"},
        {"email": "researcher@rms.com", "password": "researcher123", "role": "researcher"},
    ]
    for u in defaults:
        user_repo.save(
            email=u["email"],
            password_hash=hasher.hash(u["password"]),
            role=u["role"],
        )
    print("[SEED] Default users verified/created.")
