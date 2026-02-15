import jwt
import datetime
from typing import List, Dict, Optional
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base
from ports import ProjectDatabasePort, TokenProviderPort, ResearchApiPort, MessageBrokerPort, Project

Base = declarative_base()

class DBProject(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    ref_id = Column(String, unique=True)
    title = Column(String)
    researcher = Column(String)

# --- PILLAR 1: PERSISTENCE (Strictly Separated) ---
class SQLiteAdapter(ProjectDatabasePort):
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

class PostgresAdapter(ProjectDatabasePort):
    def __init__(self, db_url: str):
        # This will fail on purpose if no Postgres DB is running
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

class MockDBAdapter(ProjectDatabasePort):
    def __init__(self): self.projects = []
    def save(self, p): self.projects.append(p); return p
    def fetch_all(self): return self.projects

# --- PILLAR 2: IDENTITY ---
class JWTAdapter(TokenProviderPort):
    def __init__(self, secret: str): self.secret = secret
    def encode(self, p):
        data = {**p, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)}
        return jwt.encode(data, self.secret, algorithm="HS256")
    def decode(self, t):
        try: return jwt.decode(t, self.secret, algorithms=["HS256"])
        except: return None

# --- PILLAR 3: INTEGRATIONS ---
class ScholarAdapter(ResearchApiPort):
    def search_papers(self, q): return [{"source": "Scholar", "title": f"Study of {q}"}]

# --- PILLAR 4: MESSAGING ---
class LogBrokerAdapter(MessageBrokerPort):
    def publish_event(self, t, d): print(f"[EVENT-BROKER] Broadcast: {t} | Data: {d}")