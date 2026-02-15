###############################################################################
# RMS — Student-Budget Azure Deployment (FIXED)
# =========================================================================
# 
# FIXES APPLIED (503 resolution):
#   1. ACR credentials passed to App Service (DOCKER_REGISTRY_SERVER_*)
#   2. Startup command uses port 8000 consistently
#   3. WEBSITES_PORT = 8000 matches Dockerfile EXPOSE and CMD
#   4. PostgreSQL firewall allows all Azure services
#   5. App starts in SQLite mode first (won't crash if PG is slow)
#
###############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.80"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "azurerm" {
  features {}
}

# ── Variables ──
variable "project_name" {
  default = "rms"
}

variable "location" {
  description = "Azure region — pick one close to India for lower latency"
  default     = "southindia"
}

variable "pg_admin_username" {
  default = "rmsadmin"
}

variable "pg_admin_password" {
  description = "PostgreSQL password — set via TF_VAR_pg_admin_password"
  type        = string
  sensitive   = true
}

variable "jwt_secret" {
  description = "JWT signing secret — set via TF_VAR_jwt_secret"
  type        = string
  sensitive   = true
  default     = "rms-student-jwt-secret-2026"
}

# ── Resource Group ──
resource "azurerm_resource_group" "rms" {
  name     = "${var.project_name}-final-rg"
  location = var.location

  tags = {
    Project   = "RMS"
    ManagedBy = "Terraform"
    Tier      = "Free"
  }
}

# Random suffix to make names globally unique
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

###############################################################################
# PILLAR 1: PERSISTENCE — PostgreSQL Flexible Server (Free Tier)
###############################################################################

resource "azurerm_postgresql_flexible_server" "rms" {
  name                   = "${var.project_name}-pgflex-${random_string.suffix.result}"
  resource_group_name    = azurerm_resource_group.rms.name
  location               = azurerm_resource_group.rms.location
  version                = "16"
  administrator_login    = var.pg_admin_username
  administrator_password = var.pg_admin_password

  sku_name   = "B_Standard_B1ms"
  storage_mb = 32768

  backup_retention_days        = 7
  geo_redundant_backup_enabled = false

  tags = {
    Pillar = "Persistence"
    Tier   = "Free-12mo"
  }
}

resource "azurerm_postgresql_flexible_server_database" "rmsdb" {
  name      = "rmsdb"
  server_id = azurerm_postgresql_flexible_server.rms.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# FIX: Allow ALL Azure services to connect (0.0.0.0 is Azure's magic IP)
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure" {
  name             = "AllowAllAzureServices"
  server_id        = azurerm_postgresql_flexible_server.rms.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# Also allow your own IP for debugging (optional — update with your IP)
# resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_me" {
#   name             = "AllowMyIP"
#   server_id        = azurerm_postgresql_flexible_server.rms.id
#   start_ip_address = "YOUR.PUBLIC.IP.HERE"
#   end_ip_address   = "YOUR.PUBLIC.IP.HERE"
# }

resource "azurerm_postgresql_flexible_server_configuration" "require_ssl" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.rms.id
  value     = "on"
}

###############################################################################
# CONTAINER REGISTRY
###############################################################################

resource "azurerm_container_registry" "rms" {
  name                = "${var.project_name}acr${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rms.name
  location            = azurerm_resource_group.rms.location
  sku                 = "Basic"     # Basic is cheaper; Standard if you need more
  admin_enabled       = true

  tags = {
    Tier = "Free-12mo"
  }
}

###############################################################################
# COMPUTE — App Service (B1 Linux with Docker container)
###############################################################################

resource "azurerm_service_plan" "rms" {
  name                = "${var.project_name}-plan"
  resource_group_name = azurerm_resource_group.rms.name
  location            = azurerm_resource_group.rms.location
  os_type             = "Linux"
  sku_name            = "B1"

  tags = {
    Tier = "Free-12mo"
  }
}

resource "azurerm_linux_web_app" "rms" {
  name                = "${var.project_name}-app-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.rms.name
  location            = azurerm_resource_group.rms.location
  service_plan_id     = azurerm_service_plan.rms.id

  site_config {
    application_stack {
      docker_image_name   = "rms-api:latest"
      docker_registry_url = "https://${azurerm_container_registry.rms.login_server}"
    }

    # FIX: Do NOT set app_command_line — let the Dockerfile CMD handle it.
    # Setting it here OVERRIDES the Dockerfile CMD, and Azure sometimes
    # mangles the command. Your Dockerfile already has the correct CMD.

    always_on = false
  }

  app_settings = {
    #####################################################################
    # FIX 1: ACR CREDENTIALS — This was the main 503 cause!
    # Without these, App Service cannot pull your image from ACR.
    #####################################################################
    "DOCKER_REGISTRY_SERVER_URL"      = "https://${azurerm_container_registry.rms.login_server}"
    "DOCKER_REGISTRY_SERVER_USERNAME" = azurerm_container_registry.rms.admin_username
    "DOCKER_REGISTRY_SERVER_PASSWORD" = azurerm_container_registry.rms.admin_password

    #####################################################################
    # FIX 2: PORT — Must match Dockerfile EXPOSE and CMD
    # Your Dockerfile says: --port 8000
    # So WEBSITES_PORT must be 8000
    #####################################################################
    "WEBSITES_PORT" = "8000"

    #####################################################################
    # FIX 3: Start in SQLITE mode first!
    # If PostgreSQL is slow to start or unreachable, your app won't
    # crash on boot. You can switch to prod-postgres from the UI
    # dropdown once everything is running.
    #####################################################################
    "DEFAULT_ADAPTER_MODE" = "prod-sqlite"

    # Pillar 1: Persistence — Connection string ready for when you switch
    "DATABASE_URL" = "postgresql+psycopg2://${var.pg_admin_username}:${urlencode(var.pg_admin_password)}@${azurerm_postgresql_flexible_server.rms.fqdn}:5432/rmsdb?sslmode=require"

    # Pillar 2: Identity — JWTAdapter secret
    "JWT_SECRET" = var.jwt_secret

    # Python config
    "PYTHONUNBUFFERED" = "1"

    # Prevent Azure from nuking your container for slow starts
    "WEBSITES_CONTAINER_START_TIME_LIMIT" = "300"
  }

  tags = {
    Pillar = "Compute"
    Tier   = "Free-12mo"
  }

  timeouts {
    create = "30m"
    update = "30m"
  }
}

###############################################################################
# OUTPUTS
###############################################################################

output "app_url" {
  description = "Your live app URL"
  value       = "https://${azurerm_linux_web_app.rms.default_hostname}"
}

output "app_name" {
  description = "App Service name (for az commands)"
  value       = azurerm_linux_web_app.rms.name
}

output "resource_group" {
  description = "Resource group name"
  value       = azurerm_resource_group.rms.name
}

output "postgres_host" {
  description = "PostgreSQL server FQDN"
  value       = azurerm_postgresql_flexible_server.rms.fqdn
}

output "acr_login_server" {
  description = "ACR server for docker push"
  value       = azurerm_container_registry.rms.login_server
}

output "acr_name" {
  description = "ACR name (for az acr login)"
  value       = azurerm_container_registry.rms.name
}

output "monthly_cost_estimate" {
  value = "₹0 (within Azure for Students free tier limits)"
}
