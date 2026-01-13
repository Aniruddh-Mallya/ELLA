import pytest
from domain import ResearchService
from ports import Project, User, ProjectDatabasePort
from typing import List

# --- Mock Adapter (The 'Training Dummy') ---
# In Hexagonal Architecture, we don't need a real database to test the Brain!
class MockDBAdapter(ProjectDatabasePort):
    def __init__(self):
        self.projects = []
    def save(self, project: Project) -> Project:
        self.projects.append(project)
        return project
    def fetch_all(self) -> List[Project]:
        return self.projects

def test_research_service_validation():
    """Test that the 'Brain' correctly rejects bad data."""
    mock_db = MockDBAdapter()
    service = ResearchService(mock_db)
    user = User(email="admin@test.com", role="admin")
    
    # 1. Test Title Length Validation
    with pytest.raises(ValueError, match="Validation Error: Project title is too short."):
        short_project = Project(title="ABC", researcher="Goku")
        service.create_project(short_project, user)

def test_research_service_role_check():
    """Test that the 'Brain' enforces role security."""
    mock_db = MockDBAdapter()
    service = ResearchService(mock_db)
    
    # A user with 'guest' role should be rejected
    weak_user = User(email="guest@test.com", role="guest")
    project = Project(title="New Android Research", researcher="Gero")
    
    with pytest.raises(PermissionError, match="Access Denied"):
        service.create_project(project, weak_user)

def test_successful_project_creation():
    """Test the 'Happy Path' where everything works."""
    mock_db = MockDBAdapter()
    service = ResearchService(mock_db)
    user = User(email="bulma@capsule.com", role="admin")
    project = Project(title="Gravity Chamber v2", researcher="Dr. Briefs")
    
    created = service.create_project(project, user)
    assert created.title == "Gravity Chamber v2"
    assert len(mock_db.fetch_all()) == 1