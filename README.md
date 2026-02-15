# ELLA: Secure Identity & Profile Management System 

A Python backend built with the **Hexagonal (Ports & Adapters) Architecture**, containerized with Docker, and deployed to **Azure Cloud** using Terraform.

```
Browser  →  FastAPI (inbound adapter)
                │
            Domain Logic (ResearchService, AuthService)
                │
            Outbound Adapters ──→ PostgreSQL (Azure)
                                ──→ JWT Auth
                                ──→ Scholar API
                                ──→ Event Broker
```

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Auth | JWT (PyJWT) |
| Database | SQLite (local) / PostgreSQL (cloud) |
| Container | Docker |
| Cloud | Azure App Service + PostgreSQL Flexible Server |
| IaC | Terraform |

## Run Locally (Docker)

```bash
docker-compose up --build
# Visit http://localhost:8002
```

## Deploy to Azure

### Prerequisites

- [Azure Account](https://azure.microsoft.com/en-us) account 
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) installed
- [Terraform](https://developer.hashicorp.com/terraform/install) installed
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running

### Deploy (3 commands)

```powershell
cd terraform

# Set your passwords (change these!)
$env:TF_VAR_pg_admin_password = "YourSecurePassword123!"
$env:TF_VAR_jwt_secret = "your-jwt-signing-secret"

# Deploy everything
.\deploy.ps1 setup
```

This will:
1. Create a PostgreSQL database on Azure 
2. Create a container registry 
3. Create an App Service 
4. Build your Docker image and push it
5. Print your live URL

### Update After Code Changes

```powershell
cd terraform
.\deploy.ps1 push
```

### Other Commands

```powershell
.\deploy.ps1 status    # Check what's running
.\deploy.ps1 logs      # Stream container logs
.\deploy.ps1 debug     # Open /debug endpoint
.\deploy.ps1 destroy   # Delete everything (stops charges)
```

## Project Structure

```
RMS/
├── .github/workflows/   # CI/CD (GitHub Actions)
├── terraform/
│   ├── main.tf          # Azure infrastructure definition
│   └── deploy.ps1       # One-command deploy script
├── Dockerfile           # Container definition
├── docker-compose.yml   # Local development
├── ports.py             # Port interfaces (hexagonal)
├── domain.py            # Business logic
├── inbound_adapters.py  # FastAPI routes
├── outbound_adapters.py # DB, JWT, API adapters
├── index.html           # React frontend
└── requirements.txt     # Python dependencies
```

## Architecture

The app follows the **Hexagonal Architecture** pattern:

- **Ports** (`ports.py`) — Abstract interfaces for external dependencies
- **Domain** (`domain.py`) — Pure business logic, no framework imports
- **Inbound Adapters** (`inbound_adapters.py`) — FastAPI REST API
- **Outbound Adapters** (`outbound_adapters.py`) — SQLite, PostgreSQL, JWT, Scholar API

The adapter can be swapped at runtime via the `X-Adapter-Mode` header or the UI dropdown:
- `prod-sqlite` — Local SQLite database
- `prod-postgres` — Azure PostgreSQL (cloud)
- `dev-mock` — In-memory mock for testing
