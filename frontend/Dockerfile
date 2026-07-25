# Frontend (Next.js) — dev image, mirrors the local `npm run dev` workflow.
# Build context is frontend/ itself (see docker-compose.yml).
FROM node:20-slim

WORKDIR /app

# Installed in its own layer so `docker build` doesn't reinstall on every
# source change — only invalidated when package*.json changes.
COPY package*.json ./
RUN npm install

# Source is bind-mounted over this at runtime (see docker-compose.yml) so
# this COPY only matters for a one-off `docker build` without compose.
COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
