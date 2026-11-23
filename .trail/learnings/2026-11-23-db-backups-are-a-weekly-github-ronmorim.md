---
title: "DB backups are a weekly GitHub Actions pg_dump, weekly because of the free plan's egress quota"
author: RonMorim
date: 2026-11-23
branch: claude/weekly-db-backup
cost: { minutes: 2, tokens: 26842 }
id: l-6931a086
scope: repo
status: active
src: agent
touches:
  - ".github/workflows/db-backup.yml"
  - docs/backup-restore.md
  - backend/alembic_app_schema/versions/a7c31e5d9b20_rls_on_alembic_version_tables.py
---

## Decided
- The free Supabase plan has no backups. Ron chose a free self-run backup over Pro (2026-11-23): `.github/workflows/db-backup.yml` dumps `public`, `linkedin`, and the data in `auth.users`/`auth.identities`, encrypts with `age` (public key in repo variable `BACKUP_AGE_RECIPIENT`, private key only in Ron's password manager), and keeps it as a 90-day artifact.
- Weekly, not daily: each dump downloads the whole DB and counts toward the 5 GB/month egress quota, which the app alone had ~51% used in Nov 2026. Daily (~3-4 GB/month) would hit the quota and get the project restricted (402s).

## Tried and ruled out
- Supabase's own daily backups: Pro plan only.
- Uploading an unencrypted dump: the repo is public, and its artifacts and logs are visible to others.

## Watch out
- pg_dump goes through the session pooler (port 5432); the workflow rewrites 6543 to 5432. The transaction pooler can break pg_dump, and GitHub runners have no IPv6 for the direct `db.<ref>` host.
- The workflow fails if `public.profiles`, `alembic_version_app_schema` or `auth.users` has no data in the dump. An empty dump otherwise looks like a successful one.
- Restore into a NEW project, never over production; see docs/backup-restore.md.
