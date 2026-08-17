# Komet TV

Digital signage platform for BMK Komet. Displays photos, videos, announcements, and sponsors on a Google TV in a continuous loop.

## Architecture

- **Backend:** FastAPI + SQLite
- **TV Player:** Vanilla JS (public, full-screen)
- **Admin UI:** Vanilla JS (login required)
- **Deployment:** Docker on Coolify (Hostup VPS)

## Routes

| Route | Description |
|-------|-------------|
| `/display/main` | TV Player (public) |
| `/admin` | Admin UI (auth required) |
| `/api/playlist` | Playlist API |
| `/api/media` | Media upload/management API |

## Development

```bash
# Copy environment file
cp .env.example .env

# Run with Docker
docker-compose up --build

# Access
# Player: http://localhost:8000/display/main
# Admin:  http://localhost:8000/admin
```

## Deployment (Coolify)

1. Connect GitHub repo to Coolify
2. Set build pack to Docker
3. Configure persistent volumes:
   - `/app/data` → database
   - `/app/media` → uploaded media
4. Set environment variables from `.env.example`
5. Set domain to `tv.bmkkomet.se`
6. Deploy

## Persistent Volumes

| Container Path | Purpose |
|----------------|---------|
| `/app/data` | SQLite database |
| `/app/media` | Uploaded images, videos, sponsors |

## Default Admin

- Username: `admin`
- Password: `komet123`

Change immediately after first deployment.
