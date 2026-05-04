# Railway Deployment — ratethat.tennis

> **Quick reference**: Two services to deploy — the API and the frontend.
> The database and pipeline are already running on Railway.

---

## What's already running on Railway

| Service | Status | Notes |
|---|---|---|
| PostgreSQL | ✅ Running | `switchyard.proxy.rlwy.net:39343/railway` |
| Pipeline | ✅ Running | `pipeline/Dockerfile`, cron jobs configured |
| API | Deploy now ↓ | `Dockerfile` at repo root |
| Frontend | Deploy now ↓ | `frontend/Dockerfile` (nginx + Vite build) |

---

## Step 1 — Push the repo to GitHub

If you haven't already:

```bash
cd /path/to/ratethat.tennis
git add .
git commit -m "Add Railway deployment files"
git push origin main
```

---

## Step 2 — Deploy the API service

### 2a. Create the service
1. Open your Railway project → **+ New** → **GitHub Repo**
2. Select `ratethat-tennis` repo
3. Service settings → **Root Directory** → leave as `/` (repo root)
4. Railway detects `Dockerfile` + `railway.toml` automatically
5. **Don't deploy yet** — set variables first (2b)

### 2b. Link Postgres + set variables
In the API service → **Variables** tab:

1. Click **+ Add Reference** → Postgres service → `DATABASE_URL`
   (This auto-injects the internal Railway URL — faster than the public URL)

2. Add manually:

| Variable | Value |
|---|---|
| `CORS_ORIGINS` | `https://ratethat.tennis,https://www.ratethat.tennis,http://localhost:3000` |

### 2c. Deploy and verify
Click **Deploy**. Once it's up, open the Railway-assigned URL and check:
- `GET /health` → `{"status": "ok", "db": "connected"}`
- `GET /docs` → FastAPI Swagger UI (confirms the app is running)

**Copy the API URL** — you need it for Step 3. It looks like:
`https://ratethat-tennis-api-production-xxxx.up.railway.app`

---

## Step 3 — Deploy the frontend service

> ⚠️ **Set `VITE_API_URL` BEFORE the first build.** Vite bakes environment variables into the JavaScript bundle at build time — they cannot be changed without rebuilding.

### 3a. Create the service
1. Railway project → **+ New** → **GitHub Repo**
2. Same `ratethat-tennis` repo
3. Service settings → **Root Directory** → set to `frontend`
4. Railway detects `frontend/Dockerfile` + `frontend/railway.toml`
5. **Don't deploy yet** — set variables first (3b)

### 3b. Set the API URL
In the frontend service → **Variables** tab, add:

| Variable | Value |
|---|---|
| `VITE_API_URL` | The API URL from Step 2c — e.g. `https://ratethat-tennis-api-production-xxxx.up.railway.app` |

### 3c. Deploy
Click **Deploy**. Railway will:
1. Run `npm ci` to install dependencies
2. Run `npm run build` (Vite compiles React + bakes in `VITE_API_URL`)
3. Copy `dist/` into an nginx container
4. Start nginx with SPA routing (React Router works on page refresh)

### 3d. Verify
Open the Railway frontend URL — you should see the ratethat.tennis homepage.

---

## Step 4 — Connect ratethat.tennis domain

### Frontend → ratethat.tennis (apex)
1. Frontend service → **Settings** → **Networking** → **+ Custom Domain**
2. Enter `ratethat.tennis`
3. At your DNS provider, add:
   ```
   Type:  CNAME
   Name:  @ (or blank for apex)
   Value: YOUR-FRONTEND-URL.up.railway.app
   ```
   (If your registrar doesn't support apex CNAME, use an ALIAS/ANAME record)
4. Also add `www`:
   ```
   Type:  CNAME
   Name:  www
   Value: YOUR-FRONTEND-URL.up.railway.app
   ```
5. Railway provisions the SSL cert automatically. DNS propagation takes 0–30 min.

### API → api.ratethat.tennis (optional but clean)
1. API service → **Settings** → **Networking** → **+ Custom Domain**
2. Enter `api.ratethat.tennis`
3. DNS: `CNAME api → YOUR-API-URL.up.railway.app`
4. After DNS is live, update the frontend service:
   - Change `VITE_API_URL` to `https://api.ratethat.tennis`
   - Redeploy the frontend (triggers a new build with updated URL)
5. Update API service `CORS_ORIGINS` to include `https://ratethat.tennis,https://www.ratethat.tennis`

---

## Step 5 — Verify data is flowing

Run these in Railway → Postgres → **Data** → **Query**:

```sql
-- Matches in the pipeline
SELECT event_date, COUNT(*) AS matches
FROM matches
GROUP BY event_date
ORDER BY event_date DESC
LIMIT 10;

-- Player ratings populated (run_ratings.command to populate)
SELECT COUNT(*) AS rated_players FROM player_ratings WHERE rtt_score IS NOT NULL;

-- Recent pipeline jobs
SELECT job_type, status, records_fetched, completed_at
FROM pipeline_runs
ORDER BY started_at DESC
LIMIT 10;
```

If `player_ratings` is empty, run the ratings engine locally:
```bash
./run_ratings.command
```

If `matches` is empty, run the fixtures pipeline:
```bash
./run_fixtures.command
```

---

## Environment variables reference

### API service
| Variable | Description | Set via |
|---|---|---|
| `DATABASE_URL` | Railway Postgres connection string | Reference from Postgres service |
| `CORS_ORIGINS` | Comma-separated allowed origins | Manual |
| `PORT` | HTTP port | Auto-injected by Railway |

### Frontend service (build-time — baked into JS bundle)
| Variable | Description | Example |
|---|---|---|
| `VITE_API_URL` | Full URL of the deployed API | `https://api.ratethat.tennis` |
| `PORT` | nginx listen port | Auto-injected by Railway |

---

## Re-deploying after code changes

Railway auto-deploys when you push to `main` (if GitHub integration is set up with auto-deploy enabled).

Or manually: Service → **Deploy** → **Deploy Latest Commit**.

| Change type | What to do |
|---|---|
| API code change | Push → API auto-redeploys |
| Frontend code change | Push → Frontend auto-redeploys |
| `VITE_API_URL` change | Update variable → manually redeploy frontend |
| `CORS_ORIGINS` change | Update variable → API auto-restarts |

---

## Pipeline cron schedules

| Job | Cron (UTC) | Command |
|---|---|---|
| Daily fixtures (morning) | `0 6 * * *` | `python pipeline.py --job daily_fixtures` |
| Daily fixtures (results) | `30 22 * * *` | `python pipeline.py --job daily_fixtures` |
| Livescore (during play) | `*/5 * * * *` | `python pipeline.py --job livescore` |
| Weekly tournaments | `0 3 * * 1` | `python pipeline.py --job sync_tournaments` |

Configure in: Pipeline service → **Settings** → **Cron Schedule** (one schedule per service, or create multiple pipeline services each with one CMD override).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| API `/health` returns error | Check `DATABASE_URL` is linked from Postgres service |
| Frontend shows "No matches found" | Check `VITE_API_URL` is correct and has no trailing slash |
| CORS errors in browser console | Add frontend URL to API `CORS_ORIGINS` and redeploy API |
| Page refresh gives 404 | Nginx SPA routing handles this — check `frontend/nginx.conf` was included in Docker build |
| Stale API URL in frontend | `VITE_API_URL` is baked in at build time — update the variable and trigger a new deploy |
| Docker build fails on `npm ci` | Ensure `package-lock.json` is committed to git |
