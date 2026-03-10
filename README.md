# Buffet of the Month Club

An authenticated Flask app for logging buffet visits, tracking restaurants, managing members, and recording pre-buffet and post-buffet weigh-ins.

## Current architecture

- Flask server-rendered app
- SQLAlchemy models for restaurants, members, visits, weigh-ins, and admin users
- Flask-Login authentication
- SQLite for development
- Postgres-ready via `DATABASE_URL` for Azure or AWS deployment
- Optional Docker support for container platforms

## Project structure

- `app.py`: app factory, models, routes, and auth
- `templates/`: Jinja templates for public pages and admin workflows
- `static/styles.css`: site styling
- `requirements.txt`: Python dependencies
- `.env.example`: local configuration template
- `Dockerfile`: optional container deployment path

## Features in this starter

- Admin sign-in
- Admin creation by an existing admin
- Manage restaurants from the web UI
- Manage club members from the web UI
- Create, edit, and delete buffet visits
- Record per-member before and after buffet weights
- Display total gain and a buffet-by-buffet scoreboard

## Data model

### Restaurants

Stored in the database with:

- Name
- City
- Category
- Active/inactive status

### Members

Stored in the database with:

- Name
- Active/inactive status

### Visits

Each buffet visit stores:

- Restaurant reference
- Visit date
- Price per person
- Overall rating
- Visit notes

### Weigh-ins

Each visit can store weigh-ins for any active member:

- Member reference
- Before buffet weight
- After buffet weight
- Per-person gain

## Local development

### 1. Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Create your environment file

```powershell
Copy-Item .env.example .env
```

Set at least these values in `.env`:

- `SECRET_KEY`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `ADMIN_NAME`

For local development, the default SQLite connection is already set:

```env
DATABASE_URL=sqlite:///buffet_club.db
```

### 4. Run the app

```powershell
python app.py
```

Then open `http://localhost:5000`.

### 5. Initialize the database schema

For a fresh local database:

```powershell
flask --app app:app db upgrade
```

## Deployment recommendation

You said you want the container route on an Azure VM, partly because you still have credits and partly because you want AZ-104 practice. That is a reasonable choice here.

### Recommended for your goal: Azure VM + Docker Compose

Best fit if you want:

- Hands-on VM administration
- Practice with networking, NSGs, disks, updates, SSH, and container runtime setup
- A deployment model that still keeps the app itself containerized

Suggested shape:

1. Create an Ubuntu VM in Azure.
2. Open only the ports you actually need in the Network Security Group.
3. Install Docker Engine and Docker Compose on the VM.
4. Copy the repo to the VM or pull it from GitHub.
5. Create a production `.env`.
6. Run `docker compose up -d --build`.
7. Run `docker compose exec web flask --app app:app db upgrade`.
8. Use the included Nginx container as the public reverse proxy.
9. Issue a Let's Encrypt certificate, then enable the TLS Nginx config.

If you use SQLite in the container deployment, point `DATABASE_URL` at the mounted volume path:

```env
DATABASE_URL=sqlite:////app/instance/buffet_club.db
```

The repo includes:

- [docker-compose.yml](d:\repos\BoMC\docker-compose.yml)
- [nginx/conf.d/default.conf](d:\repos\BoMC\nginx\conf.d\default.conf)
- [nginx/conf.d/tls.conf.example](d:\repos\BoMC\nginx\conf.d\tls.conf.example)
- [scripts/bootstrap-ubuntu.sh](d:\repos\BoMC\scripts\bootstrap-ubuntu.sh)
- [scripts/deploy.sh](d:\repos\BoMC\scripts\deploy.sh)
- [scripts/backup-sqlite.sh](d:\repos\BoMC\scripts\backup-sqlite.sh)

Use the HTTP-only Nginx config first. After the certificate is issued, copy `tls.conf.example` to `tls.conf`, replace the placeholder domain names, and reload the Nginx container.

### Database choice for the VM path

You have two reasonable options:

#### Option A: SQLite on the VM

Good for:

- Cheap first deployment
- Minimal moving parts
- Personal project scale

Tradeoff:

- The database lives on the VM disk
- Backups and recovery are your responsibility
- Not ideal if you later scale beyond one instance

#### Option B: Azure Database for PostgreSQL

Good for:

- Better durability
- Easier future scaling
- Cleaner separation between app compute and data

Tradeoff:

- Higher baseline cost than SQLite
- More Azure resources to manage

For your first deployment on credits, SQLite on the VM is acceptable. If the app becomes important or you want better operational discipline, move to PostgreSQL.

### Other Azure options

If you later decide you want less VM management:

- `Azure App Service` is simpler operationally
- `Azure Container Apps` is a cleaner container platform

Those are good platforms, but they do less for your AZ-104 practice than a VM does.

### AWS fallback

If you switch clouds later, the closest equivalent is:

- EC2 + Docker Compose

That keeps the operating model similar.

## Important note about schema changes

This project now uses Flask-Migrate/Alembic for schema management.

Common commands:

```powershell
flask --app app:app db upgrade
flask --app app:app db migrate -m "describe change"
flask --app app:app db downgrade
```

The initial migration lives in [migrations/versions/20260310_000001_initial_schema.py](d:\repos\BoMC\migrations\versions\20260310_000001_initial_schema.py).

For the Azure VM/container path, run migrations after deploy and before exposing the app publicly.

## Azure VM runbook

Use the detailed deployment guide in [deploy/azure-vm.md](d:\repos\BoMC\deploy\azure-vm.md).

## VM operations

### First-time VM setup

On the VM:

```bash
chmod +x scripts/bootstrap-ubuntu.sh scripts/deploy.sh
./scripts/bootstrap-ubuntu.sh
```

Then:

1. Log out and back in so the `docker` group membership applies.
2. Edit `.env`.
3. Run `./scripts/deploy.sh`.

### Normal redeploy

On the VM:

```bash
cd ~/TheBoMC
./scripts/deploy.sh
```

### SQLite backup

On the VM:

```bash
cd ~/TheBoMC
chmod +x scripts/backup-sqlite.sh
./scripts/backup-sqlite.sh
```

Backups are written into [backups](d:\repos\BoMC\backups).

The script:

- uses SQLite's backup API from inside the running web container
- writes timestamped snapshots into `backups/`
- deletes backups older than `14` days by default

You can override retention:

```bash
KEEP_DAYS=30 ./scripts/backup-sqlite.sh
```

## Next steps worth doing

1. Add delete/archive flows for restaurants and members with guardrails around historical data.
2. Add photo uploads for each buffet visit.
3. Add role separation if you want non-admin authenticated users later.
