import os
import jwt
import datetime
from typing import List, Dict, Optional
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base
from ports import ProjectDatabasePort, TokenProviderPort, Project

# --- Infrastructure: SQLite (The 'Wall Socket') ---
Base = declarative_base()

class DBProject(Base):
    """The raw database row format used by SQLAlchemy."""
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    ref_id = Column(String, unique=True, index=True) 
    title = Column(String)
    researcher = Column(String)
    status = Column(String)

class ProjectMapper:
    """The 'Power Brick' - Explicitly translates SQL rows to Domain objects."""
    @staticmethod
    def to_domain(db_item: DBProject) -> Project:
        return Project(
            reference_id=db_item.ref_id,
            title=db_item.title,
            researcher=db_item.researcher,
            status=db_item.status
        )

    @staticmethod
    def from_domain(domain_item: Project) -> DBProject:
        return DBProject(
            ref_id=domain_item.reference_id,
            title=domain_item.title,
            researcher=domain_item.researcher,
            status=domain_item.status
        )

class SQLiteAdapter(ProjectDatabasePort):
    def __init__(self, db_url: str = "sqlite:////app/data/research.db"):
        # We use an absolute path inside the /app/data volume for reliability
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.mapper = ProjectMapper()

    def save(self, project: Project) -> Project:
        with self.SessionLocal() as db:
            db_item = self.mapper.from_domain(project)
            db.add(db_item)
            db.commit()
            return project

    def fetch_all(self) -> List[Project]:
        with self.SessionLocal() as db:
            db_items = db.query(DBProject).all()
            return [self.mapper.to_domain(item) for item in db_items]

# --- Security: JWT Implementation ---
class JWTAdapter(TokenProviderPort):
    def __init__(self):
        self.secret = os.getenv("JWT_SECRET", "rms_dev_secret_key")
        self.algorithm = "HS256"
        """
        Generates a JWT token from the given payload.

        :param payload: A dictionary of data to be encoded in the JWT token.
        :return: A string representing the JWT token.
        """
    def encode(self, payload: Dict) -> str:
        data = {**payload, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)}
        return jwt.encode(data, self.secret, algorithm=self.algorithm)

    def decode(self, token: str) -> Optional[Dict]:
        try:
            return jwt.decode(token, self.secret, algorithms=[self.algorithm])
        except Exception:
            return None