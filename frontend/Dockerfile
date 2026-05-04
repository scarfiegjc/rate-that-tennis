# ratethat.tennis — Frontend service
# Multi-stage build: Node.js builds the Vite app, nginx serves the static output.
#
# Railway deployment: set root directory to frontend/, Dockerfile path to ./Dockerfile
#
# Build-time environment variables required on Railway:
#   VITE_API_URL  — e.g. https://api-production-xxxx.up.railway.app
#                   (set this BEFORE deploying — it gets baked into the JS bundle)

# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (better layer caching)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build
# VITE_API_URL must be set as a Railway build variable — Vite bakes it in at build time
COPY . .
RUN npm run build

# ── Stage 2: Serve with nginx ─────────────────────────────────────────────────
FROM nginx:alpine

# Copy built assets from stage 1
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config (uses $PORT injected by Railway via envsubst)
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Railway injects PORT — envsubst replaces $PORT in the nginx template on startup
# nginx:alpine base image runs envsubst automatically for /etc/nginx/templates/*.template
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
