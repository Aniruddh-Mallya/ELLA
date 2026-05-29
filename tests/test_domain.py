import pytest
from domain import ResearchService, ProfileService
from ports import (
    Project, User, Paper,
    ProjectDatabasePort, ResearchApiPort, MessageBrokerPort, UserRepositoryPort,
)
from typing import List, Dict, Optional

# --- 1. THE TRAINING DUMMIES (Mock Outbound Adapters) ---

class MockDBAdapter(ProjectDatabasePort):
    """Pillar 1 Mock: Simulation for SQLite/Postgres."""
    def __init__(self):
        self.projects = []
        self.papers: Dict[str, List[Paper]] = {}
    def save(self, project: Project) -> Project:
        self.projects.append(project)
        return project
    def fetch_all(self) -> List[Project]:
        return self.projects
    def fetch_by_ref(self, reference_id: str) -> Optional[Project]:
        return next((p for p in self.projects if p.reference_id == reference_id), None)
    def save_paper(self, project_ref_id: str, paper: Paper) -> Paper:
        self.papers.setdefault(project_ref_id, []).append(paper)
        return paper
    def fetch_papers(self, project_ref_id: str) -> List[Paper]:
        return list(self.papers.get(project_ref_id, []))
    def remove_paper(self, project_ref_id: str, paper_id: str) -> bool:
        items = self.papers.get(project_ref_id, [])
        for idx, p in enumerate(items):
            if p.paper_id == paper_id:
                items.pop(idx)
                return True
        return False

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

class MockUserRepo(UserRepositoryPort):
    """Pillar 1b Mock: in-memory user store incl. profile fields."""
    def __init__(self):
        self.users: Dict[str, Dict] = {}
    def get_by_email(self, email: str) -> Optional[Dict]:
        return self.users.get(email)
    def save(self, email: str, password_hash: str, role: str) -> None:
        self.users.setdefault(email, {
            "email": email, "role": role, "password_hash": password_hash,
            "full_name": None, "institution": None, "orcid_id": None,
        })
    def fetch_all(self) -> List[Dict]:
        return [{"email": u["email"], "role": u["role"]} for u in self.users.values()]
    def update_role(self, email: str, new_role: str) -> bool:
        if email not in self.users:
            return False
        self.users[email]["role"] = new_role
        return True
    def delete(self, email: str) -> bool:
        return self.users.pop(email, None) is not None
    def get_profile(self, email: str) -> Optional[Dict]:
        u = self.users.get(email)
        if u is None:
            return None
        return {k: u.get(k) for k in ("email", "role", "full_name", "institution", "orcid_id")}
    def update_profile(self, email, full_name, institution, orcid_id) -> bool:
        if email not in self.users:
            return False
        self.users[email].update(full_name=full_name, institution=institution, orcid_id=orcid_id)
        return True


def _research_service(db=None, api=None, broker=None, repo=None):
    """Helper that wires a ResearchService with sensible mock defaults."""
    return ResearchService(
        db or MockDBAdapter(),
        api or MockApiAdapter(),
        broker or MockBrokerAdapter(),
        repo or MockUserRepo(),
    )

# --- 2. THE TEST BENCH (Core Logic Verification) ---

def test_research_service_validation():
    """Test that the 'Brain' correctly rejects bad data."""
    service = _research_service()
    user = User(email="admin@test.com", role="admin")

    # Test Title Length Validation (Min 5 chars as per domain rules)
    with pytest.raises(ValueError, match="Validation Error: Title must be at least 5 chars."):
        service.create_project(Project(title="ABC"), user)

def test_research_service_role_check():
    """Test that the 'Brain' enforces role security."""
    service = _research_service()

    # A user with 'guest' role should be rejected by the Core logic
    weak_user = User(email="guest@test.com", role="guest")
    with pytest.raises(PermissionError, match="Access Denied"):
        service.create_project(Project(title="New Android Research"), weak_user)

def test_successful_project_creation_and_messaging():
    """Test the 'Happy Path' including Pillar 1 and Pillar 4 interactions."""
    mock_db = MockDBAdapter()
    mock_broker = MockBrokerAdapter()
    service = _research_service(db=mock_db, broker=mock_broker)

    user = User(email="bulma@capsule.com", role="admin")
    created = service.create_project(Project(title="Gravity Chamber v2"), user)

    assert created.title == "Gravity Chamber v2"
    assert len(mock_db.fetch_all()) == 1  # Verify Pillar 1 (Storage)
    assert len(mock_broker.events_sent) == 1  # Verify Pillar 4 (Messaging)
    assert mock_broker.events_sent[0]["type"] == "PROJECT_CREATED"


# --- 3. PROJECT OWNERSHIP (linked to a real authenticated user) ---

def test_create_project_assigns_owner_from_logged_in_user():
    """The project owner is taken from the caller, never typed in."""
    repo = MockUserRepo()
    repo.save("bulma@capsule.com", "h", "researcher")
    repo.update_profile("bulma@capsule.com", "Bulma Briefs", "Capsule Corp", None)
    service = _research_service(repo=repo)

    user = User(email="bulma@capsule.com", role="researcher")
    created = service.create_project(Project(title="Gravity Chamber v2"), user)
    assert created.owner_email == "bulma@capsule.com"

def test_project_listing_shows_owner_name_and_institution():
    """Listing enriches each project with the owner's real profile."""
    repo = MockUserRepo()
    repo.save("bulma@capsule.com", "h", "researcher")
    repo.update_profile("bulma@capsule.com", "Bulma Briefs", "Capsule Corp", None)
    service = _research_service(repo=repo)

    user = User(email="bulma@capsule.com", role="researcher")
    service.create_project(Project(title="Gravity Chamber v2"), user)

    views = service.get_all_projects()
    assert views[0].owner_name == "Bulma Briefs"
    assert views[0].owner_institution == "Capsule Corp"

def test_project_listing_falls_back_to_email_when_no_name():
    """If the owner hasn't set a name, display falls back to their email."""
    repo = MockUserRepo()
    repo.save("nameless@x.com", "h", "researcher")  # no profile name set
    service = _research_service(repo=repo)

    user = User(email="nameless@x.com", role="researcher")
    service.create_project(Project(title="Anonymous Study"), user)

    views = service.get_all_projects()
    assert views[0].owner_name == "nameless@x.com"


# --- 4. PAPER SEARCH (Pillar 3) ---

def test_search_papers_happy_path():
    """Search returns typed Paper objects and emits a PAPER_SEARCH event."""
    mock_broker = MockBrokerAdapter()
    service = _research_service(broker=mock_broker)

    results = service.search_papers("quantum computing", limit=2)

    assert len(results) == 2
    assert all(isinstance(p, Paper) for p in results)
    assert "quantum computing" in results[0].title
    assert mock_broker.events_sent[0]["type"] == "PAPER_SEARCH"
    assert mock_broker.events_sent[0]["data"]["count"] == 2

def test_search_papers_rejects_short_query():
    """Queries under 2 characters are rejected before any API call."""
    service = _research_service()
    with pytest.raises(ValueError, match="at least 2 characters"):
        service.search_papers("a")

def test_search_papers_rejects_bad_limit():
    """limit outside 1..25 is rejected by the domain."""
    service = _research_service()
    with pytest.raises(ValueError, match="limit must be between"):
        service.search_papers("valid query", limit=100)


# --- 4b. SAVED PAPERS (search → project loop) ---

def _owned_project(service, owner_email):
    """Create a project owned by owner_email and return it."""
    user = User(email=owner_email, role="researcher")
    return service.create_project(Project(title="Quantum Research Lab"), user)


def test_owner_can_save_paper_to_project():
    db = MockDBAdapter()
    broker = MockBrokerAdapter()
    service = _research_service(db=db, broker=broker)
    owner = User(email="ada@x.com", role="researcher")
    project = _owned_project(service, "ada@x.com")

    paper = Paper(paper_id="W1", title="On Computable Numbers", source="OpenAlex")
    service.save_paper_to_project(project.reference_id, paper, owner)

    saved = service.get_project_papers(project.reference_id)
    assert [p.paper_id for p in saved] == ["W1"]
    assert any(e["type"] == "PAPER_SAVED" for e in broker.events_sent)


def test_non_owner_cannot_save_paper():
    service = _research_service()
    _owned_project(service, "ada@x.com")
    project = service.get_all_projects()[0]

    intruder = User(email="eve@x.com", role="researcher")
    paper = Paper(paper_id="W1", title="Sneaky Paper", source="OpenAlex")
    with pytest.raises(PermissionError, match="Only the project owner"):
        service.save_paper_to_project(project.reference_id, paper, intruder)


def test_admin_cannot_save_to_someone_elses_project():
    """Ownership is the only gate — admin gets no override."""
    service = _research_service()
    _owned_project(service, "ada@x.com")
    project = service.get_all_projects()[0]

    admin = User(email="admin@x.com", role="admin")
    paper = Paper(paper_id="W1", title="Admin Overreach", source="OpenAlex")
    with pytest.raises(PermissionError, match="Only the project owner"):
        service.save_paper_to_project(project.reference_id, paper, admin)


def test_cannot_save_same_paper_twice():
    service = _research_service()
    owner = User(email="ada@x.com", role="researcher")
    project = _owned_project(service, "ada@x.com")

    paper = Paper(paper_id="W1", title="Dup", source="OpenAlex")
    service.save_paper_to_project(project.reference_id, paper, owner)
    with pytest.raises(ValueError, match="already saved"):
        service.save_paper_to_project(project.reference_id, paper, owner)


def test_save_to_missing_project_raises():
    service = _research_service()
    owner = User(email="ada@x.com", role="researcher")
    paper = Paper(paper_id="W1", title="Orphan", source="OpenAlex")
    with pytest.raises(ValueError, match="Project not found"):
        service.save_paper_to_project("does-not-exist", paper, owner)


def test_owner_can_remove_saved_paper():
    db = MockDBAdapter()
    broker = MockBrokerAdapter()
    service = _research_service(db=db, broker=broker)
    owner = User(email="ada@x.com", role="researcher")
    project = _owned_project(service, "ada@x.com")
    service.save_paper_to_project(project.reference_id, Paper(paper_id="W1", title="X"), owner)

    service.remove_paper_from_project(project.reference_id, "W1", owner)
    assert service.get_project_papers(project.reference_id) == []
    assert any(e["type"] == "PAPER_REMOVED" for e in broker.events_sent)


def test_non_owner_cannot_remove_paper():
    service = _research_service()
    owner = User(email="ada@x.com", role="researcher")
    project = _owned_project(service, "ada@x.com")
    service.save_paper_to_project(project.reference_id, Paper(paper_id="W1", title="X"), owner)

    intruder = User(email="eve@x.com", role="researcher")
    with pytest.raises(PermissionError, match="Only the project owner"):
        service.remove_paper_from_project(project.reference_id, "W1", intruder)


def test_remove_missing_paper_raises():
    service = _research_service()
    owner = User(email="ada@x.com", role="researcher")
    project = _owned_project(service, "ada@x.com")
    with pytest.raises(ValueError, match="Paper not found"):
        service.remove_paper_from_project(project.reference_id, "ghost", owner)


def test_listing_papers_is_open_and_isolated_per_project():
    service = _research_service()
    owner = User(email="ada@x.com", role="researcher")
    p1 = _owned_project(service, "ada@x.com")
    p2 = service.create_project(Project(title="Second Lab"), owner)
    service.save_paper_to_project(p1.reference_id, Paper(paper_id="W1", title="A"), owner)

    # Any logged-in user can read; papers stay scoped to their own project
    assert [p.paper_id for p in service.get_project_papers(p1.reference_id)] == ["W1"]
    assert service.get_project_papers(p2.reference_id) == []


# --- 5. RESEARCHER PROFILE (self-service) ---

def test_update_profile_requires_full_name():
    repo = MockUserRepo()
    repo.save("r@x.com", "h", "researcher")
    svc = ProfileService(repo)
    caller = User(email="r@x.com", role="researcher")
    with pytest.raises(ValueError, match="Full name is required"):
        svc.update_my_profile(caller, full_name="  ", institution="MIT", orcid_id=None)

def test_update_profile_validates_orcid():
    repo = MockUserRepo()
    repo.save("r@x.com", "h", "researcher")
    svc = ProfileService(repo)
    caller = User(email="r@x.com", role="researcher")
    with pytest.raises(ValueError, match="ORCID"):
        svc.update_my_profile(caller, full_name="Ada", institution=None, orcid_id="not-an-orcid")

def test_update_profile_happy_path():
    repo = MockUserRepo()
    repo.save("r@x.com", "h", "researcher")
    svc = ProfileService(repo)
    caller = User(email="r@x.com", role="researcher")

    result = svc.update_my_profile(
        caller,
        full_name="Ada Lovelace",
        institution="Analytical Engine Co",
        orcid_id="0000-0002-1825-0097",
    )
    assert result["full_name"] == "Ada Lovelace"
    assert result["institution"] == "Analytical Engine Co"
    assert result["orcid_id"] == "0000-0002-1825-0097"

def test_update_profile_only_touches_callers_own_record():
    """A caller editing their profile must never affect another user."""
    repo = MockUserRepo()
    repo.save("me@x.com", "h", "researcher")
    repo.save("victim@x.com", "h", "researcher")
    repo.update_profile("victim@x.com", "Original Name", "Original Inst", None)
    svc = ProfileService(repo)

    caller = User(email="me@x.com", role="researcher")
    svc.update_my_profile(caller, full_name="My Name", institution="My Inst", orcid_id=None)

    # The other user's profile is untouched
    assert repo.get_profile("victim@x.com")["full_name"] == "Original Name"
