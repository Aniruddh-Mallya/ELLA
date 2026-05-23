import pytest
from domain import ResearchService
from ports import Project, User, Paper, ProjectDatabasePort, ResearchApiPort, MessageBrokerPort
from typing import List, Dict

# --- 1. THE TRAINING DUMMIES (Mock Outbound Adapters) ---

class MockDBAdapter(ProjectDatabasePort):
    """Pillar 1 Mock: Simulation for SQLite/Postgres."""
    def __init__(self):
        self.projects = []
    def save(self, project: Project) -> Project:
        self.projects.append(project)
        return project
    def fetch_all(self) -> List[Project]:
        return self.projects

class MockApiAdapter(ResearchApiPort):
    """Pillar 3 Mock: Simulation for the research-literature API."""
    def search_papers(self, query: str, limit: int = 10) -> List[Paper]:
        return [
            Paper(paper_id=f"test:{i}", title=f"Mock Result for {query}", source="Test")
            for i in range(min(limit, 2))
        ]

class MockBrokerAdapter(MessageBrokerPort):
    """Pillar 4 Mock: Simulation for Messaging/Events."""
    def __init__(self):
        self.events_sent = []
    def publish_event(self, event_type: str, data: Dict) -> None:
        self.events_sent.append({"type": event_type, "data": data})

# --- 2. THE TEST BENCH (Core Logic Verification) ---

def test_research_service_validation():
    """Test that the 'Brain' correctly rejects bad data."""
    # Solder all 4 pillars using mocks
    service = ResearchService(MockDBAdapter(), MockApiAdapter(), MockBrokerAdapter())
    user = User(email="admin@test.com", role="admin")
    
    # Test Title Length Validation (Min 5 chars as per new domain rules)
    with pytest.raises(ValueError, match="Validation Error: Title must be at least 5 chars."):
        short_project = Project(title="ABC", researcher="Goku")
        service.create_project(short_project, user)

def test_research_service_role_check():
    """Test that the 'Brain' enforces role security."""
    service = ResearchService(MockDBAdapter(), MockApiAdapter(), MockBrokerAdapter())
    
    # A user with 'guest' role should be rejected by the Core logic
    weak_user = User(email="guest@test.com", role="guest")
    project = Project(title="New Android Research", researcher="Gero")
    
    with pytest.raises(PermissionError, match="Access Denied"):
        service.create_project(project, weak_user)

def test_successful_project_creation_and_messaging():
    """Test the 'Happy Path' including Pillar 1 and Pillar 4 interactions."""
    mock_db = MockDBAdapter()
    mock_broker = MockBrokerAdapter()
    service = ResearchService(mock_db, MockApiAdapter(), mock_broker)
    
    user = User(email="bulma@capsule.com", role="admin")
    project = Project(title="Gravity Chamber v2", researcher="Dr. Briefs")
    
    # Execute logic
    created = service.create_project(project, user)
    
    # Assertions
    assert created.title == "Gravity Chamber v2"
    assert len(mock_db.fetch_all()) == 1  # Verify Pillar 1 (Storage)
    assert len(mock_broker.events_sent) == 1  # Verify Pillar 4 (Messaging)
    assert mock_broker.events_sent[0]["type"] == "PROJECT_CREATED"


# --- 3. PAPER SEARCH (Pillar 3) ---

def test_search_papers_happy_path():
    """Search returns typed Paper objects and emits a PAPER_SEARCH event."""
    mock_broker = MockBrokerAdapter()
    service = ResearchService(MockDBAdapter(), MockApiAdapter(), mock_broker)

    results = service.search_papers("quantum computing", limit=2)

    assert len(results) == 2
    assert all(isinstance(p, Paper) for p in results)
    assert "quantum computing" in results[0].title
    assert mock_broker.events_sent[0]["type"] == "PAPER_SEARCH"
    assert mock_broker.events_sent[0]["data"]["count"] == 2


def test_search_papers_rejects_short_query():
    """Queries under 2 characters are rejected before any API call."""
    service = ResearchService(MockDBAdapter(), MockApiAdapter(), MockBrokerAdapter())
    with pytest.raises(ValueError, match="at least 2 characters"):
        service.search_papers("a")


def test_search_papers_rejects_bad_limit():
    """limit outside 1..25 is rejected by the domain."""
    service = ResearchService(MockDBAdapter(), MockApiAdapter(), MockBrokerAdapter())
    with pytest.raises(ValueError, match="limit must be between"):
        service.search_papers("valid query", limit=100)