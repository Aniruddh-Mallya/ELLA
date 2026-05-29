# ELLA: Secure Identity & Profile Management System

A Python backend built with the **Hexagonal (Ports & Adapters) Architecture**, containerized with Docker, and run entirely on your local machine.

```
Browser  →  FastAPI (inbound adapter)
                │
            Domain Logic (ResearchService, AuthService)
                │
            Outbound Adapters ──→ SQLite (local file)
                                ──→ PostgreSQL (local container)
                                ──→ JWT Auth + Bcrypt
                                ──→ OpenAlex (paper search)
                                ──→ Event Broker
```

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Auth | JWT (PyJWT) + Bcrypt password hashing |
| Database | SQLite (file) and PostgreSQL (container) — swappable at runtime |
| Container | Docker + Docker Compose |
| CI | GitHub Actions (tests + Docker build verification) |

## Run Locally

First, create your local secrets file (it's gitignored, so your passwords never get committed):

```bash
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
# then edit .env and set ADMIN_PASSWORD, RESEARCHER_PASSWORD, and JWT_SECRET
```

Then bring up the API and a local Postgres in one command:

```bash
docker-compose up --build
# Visit http://localhost:8002
```

That starts two containers:
- `rms_consolidated_service` — the FastAPI app on port 8002
- `rms_postgres` — Postgres 16 on port 5432, data persisted in a named volume (`rms_pgdata`)

On first boot the app seeds default users into **both** SQLite and Postgres so the runtime adapter switch works without re-seeding.

> **Upgrading from an older build?** The database schema changed (researcher
> profiles, project ownership, and saved papers). Reset your local data once so
> the new tables are created cleanly:
> ```bash
> docker-compose down -v     # drops the Postgres volume
> del data\research.db       # Windows: remove the SQLite file (rm on macOS/Linux)
> docker-compose up --build
> ```

**Login credentials:** there are no built-in passwords. On first boot the app
creates the admin and researcher accounts from the values you set in `.env`
(`ADMIN_EMAIL` / `ADMIN_PASSWORD` and `RESEARCHER_EMAIL` / `RESEARCHER_PASSWORD`).
An account is only created if its password is set — log in with whatever you chose.

## Paper Search

Search the global academic literature from the **Paper Search** tab (available to every logged-in user).

- **Provider:** [OpenAlex](https://openalex.org) — free, no API key, ~220M papers, rich metadata (authors, venue, year, citation counts, abstracts, open-access PDF links).
- **Endpoint:** `GET /api/papers/search?q=<query>&limit=<1-25>` (requires a valid login token).
- **Swappable:** the provider is just another adapter behind `ResearchApiPort`. Send header `X-Research-Api: mock` (or set `RESEARCH_API_MODE=mock`) to use an offline stub with no network calls — handy for tests and demos.

```bash
curl "http://localhost:8002/api/papers/search?q=quantum%20computing&limit=5" \
  -H "Authorization: Bearer <your-token>"
```

## Saving Papers to Projects

Closes the loop between search and projects: a researcher can save any search result into one of their own projects, and each project lists everything saved to it.

- **Save** a paper: `POST /api/projects/{ref_id}/papers` — body is the paper object from the search results
- **List** a project's saved papers: `GET /api/projects/{ref_id}/papers`
- **Remove** a saved paper: `DELETE /api/projects/{ref_id}/papers?paper_id=<id>`

Rules:
- **Owner-only writes:** only the researcher who owns a project can save or remove its papers — there is no admin override. Viewing a project's saved papers is open to any logged-in user.
- **Full snapshots:** the complete paper (title, authors, year, venue, citations, abstract, links) is stored, so a project displays its papers straight from the database without re-querying OpenAlex.
- The same paper can't be saved twice to the same project.

In the UI: each search result has a **Save to project** dropdown (listing only your own projects); open a project on the **Projects** tab to reveal its saved papers, each with a **Remove** button shown only to the owner.

## Researcher Profiles & Project Ownership

- **Profiles:** every user has a profile — full name (required), institution (optional), and an optional ORCID iD. Edit yours from the **My Profile** tab. Profiles are strictly self-service: there is no endpoint to edit another user's profile, so an admin can never edit a researcher's profile.
  - `GET /api/profile` — your own profile
  - `PUT /api/profile` — update your own profile `{full_name, institution, orcid_id}`
- **Project ownership:** a project automatically belongs to whoever creates it (taken from the login token — there's no typed-in name). Project listings show the owner's real name and institution, falling back to their email if no name is set yet.

## Choosing the Database

Which backing store the app uses is an **operator decision**, set with the
`DEFAULT_ADAPTER_MODE` environment variable — not something end users can change.
The whole app runs on whichever adapter you pick:

- `prod-sqlite` — Local SQLite file at `./data/research.db` (default)
- `prod-postgres` — Local Postgres container
- `dev-mock` — In-memory mock, useful for tests

To swap, change `DEFAULT_ADAPTER_MODE` in your `.env` (or `docker-compose.yml`) and
restart. It's the same swappable hexagonal pattern as the paper-search provider —
just selected by configuration rather than per request.

## Environment Variables

Secrets live in a gitignored `.env` file (copy `.env.example` to start); `docker-compose.yml` reads them. For running outside Docker, the non-secret defaults in [inbound_adapters.py](inbound_adapters.py) are used.

| Variable | Purpose | Default |
|---|---|---|
| `ADMIN_EMAIL` | Email for the seeded admin account | `admin@rms.com` |
| `ADMIN_PASSWORD` | Admin password — account only seeds if set | _(unset — no default)_ |
| `RESEARCHER_EMAIL` | Email for the seeded researcher account | `researcher@rms.com` |
| `RESEARCHER_PASSWORD` | Researcher password — account only seeds if set | _(unset)_ |
| `JWT_SECRET` | JWT signing key | _(unset → random key per boot; set it so logins survive restarts)_ |
| `DATABASE_URL` | Postgres connection string | `postgresql+psycopg2://rmsadmin:rmsadmin@postgres:5432/rmsdb` |
| `DEFAULT_ADAPTER_MODE` | Which database the whole app uses: `prod-sqlite`, `prod-postgres`, or `dev-mock` | `prod-sqlite` |
| `RESEARCH_API_MODE` | Paper-search provider: `openalex` or `mock` | `openalex` |
| `OPENALEX_EMAIL` | Optional contact email for OpenAlex's faster polite pool | `""` |

## Project Structure

```
ELLA/
├── .github/workflows/
│   └── main.yml         # CI: tests + Docker build verification
├── Dockerfile           # Container definition
├── docker-compose.yml   # API + local Postgres
├── ports.py             # Port interfaces (hexagonal)
├── domain.py            # Business logic (zero infra imports)
├── inbound_adapters.py  # FastAPI routes + dependency injection
├── outbound_adapters.py # SQLite, Postgres, JWT, Bcrypt, OpenAlex paper search
├── index.html           # React frontend
├── requirements.txt     # Python dependencies
└── tests/               # Domain diagnostics
```

## Architecture

![Hexagonal Architecture](out/docs/diagrams/hexagonal-architecture.svg)

The app follows the **Hexagonal Architecture** pattern with strict layer separation:

- **Ports** ([ports.py](ports.py)) — Abstract interfaces that define what the domain needs
- **Domain** ([domain.py](domain.py)) — Pure business logic with zero infrastructure imports
- **Inbound Adapters** ([inbound_adapters.py](inbound_adapters.py)) — FastAPI REST API + dependency factories
- **Outbound Adapters** ([outbound_adapters.py](outbound_adapters.py)) — SQLite, PostgreSQL, JWT, Bcrypt, OpenAlex paper search

### Adapter Symmetry

```
ResearchService → ProjectDatabasePort → SQLite/Postgres ProjectAdapter
AuthService     → UserRepositoryPort  → SQLite/Postgres UserAdapter
```

### Authentication Flow

![Authentication Sequence](out/docs/diagrams/authentication-sequence.svg)

1. User submits email + password
2. `AuthService` fetches user record via `UserRepositoryPort` (database-agnostic)
3. Password is verified via `PasswordHasherPort` (bcrypt)
4. On success, a JWT token is issued via `TokenProviderPort`
5. Subsequent API calls include the JWT in the `Authorization` header
6. `AuthService.authorize()` decodes the token to identify the user

The domain layer ([domain.py](domain.py)) never imports SQLAlchemy, bcrypt, or any infrastructure library.

## Tests

```bash
pip install -r requirements.txt pytest pytest-asyncio httpx
pytest tests/test_domain.py
```

CI runs the same tests plus a Docker build verification on every push and PR.
