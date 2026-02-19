# Installation

- [Pre-built Image (Recommended)](#option-1-pre-built-image-recommended)
- [Build from Source (Docker)](#option-2-build-from-source-docker)
- [Local Installation](#option-3-local-installation)
- [Docker Volumes](#docker-volumes)

---

## Option 1: Pre-built Image (Recommended)

The easiest way to run Backlogia—no cloning or building required.

1. **Create a directory for Backlogia**
   ```bash
   mkdir backlogia && cd backlogia
   ```

2. **Download the configuration files**
   ```bash
   curl -O https://raw.githubusercontent.com/sam1am/backlogia/main/.env.example
   curl -O https://raw.githubusercontent.com/sam1am/backlogia/main/docker-compose.ghcr.yml
   ```

3. **Create your environment file**
   ```bash
   cp .env.example .env
   ```

4. **Edit `.env` with your settings** (see [Configuration](configuration.md))

5. **Start the container**
   ```bash
   docker compose -f docker-compose.ghcr.yml up -d
   ```

6. **Access Backlogia** at [http://localhost:5050](http://localhost:5050)

### Updating (Pre-built Image)

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

---

## Option 2: Build from Source (Docker)

Build the image locally from the repository.

1. **Clone the repository**
   ```bash
   git clone https://github.com/sam1am/backlogia.git
   cd backlogia
   ```

2. **Create your environment file**
   ```bash
   cp .env.example .env
   ```

3. **Edit `.env` with your settings** (see [Configuration](configuration.md))

4. **Start the container**
   ```bash
   docker compose up -d
   ```

5. **Access Backlogia** at [http://localhost:5050](http://localhost:5050)

### Updating (Build from Source)

```bash
git pull
docker compose down
docker compose up -d --build
```

---

## Option 3: Local Installation

### Prerequisites

- **Python 3.11+**
- API keys for the stores you want to sync (see [Configuration](configuration.md))

#### Amazon Games Prerequisites

1. Build the latest `nile` code: https://github.com/imLinguin/nile?tab=readme-ov-file#setting-up-dev-environment
2. Compile `nile` into an executable: https://github.com/imLinguin/nile?tab=readme-ov-file#building-pyinstaller-executable
3. Make sure that the compiled executable is in your `PATH` (either place it in an existing `PATH` folder or add the folder containing the executable to the `PATH` list)
4. If you added a new folder to your `PATH` above, open a **new terminal** for the instructions below (so it receives the updated `PATH`)

### Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/sam1am/backlogia.git
   cd backlogia
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create your environment file**
   ```bash
   cp .env.example .env
   ```

5. **Edit `.env` with your settings** (see [Configuration](configuration.md))

6. **Run the application**
   ```bash
   python web/app.py
   ```

7. **Access Backlogia** at [http://localhost:5050](http://localhost:5050)

### Updating (Local Installation)

```bash
git pull
pip install -r requirements.txt
```

Then restart the application.

---

## Docker Volumes

| Volume | Purpose |
|--------|---------|
| `./data:/data` | Database and persistent storage |
| `./data/legendary:/root/.config/legendary` | Epic Games authentication cache |
| `./data/nile:/root/.config/nile` | Amazon Games authentication cache |
| `${GOG_DB_DIR}:/gog:ro` | GOG Galaxy database (read-only) |
| `${LOCAL_GAMES_DIR_N}:/local-games-N:ro` | Local games folders 1-5 (read-only, add more in docker-compose.yml if needed) |
