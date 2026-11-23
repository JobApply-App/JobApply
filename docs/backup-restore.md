# Database backup and restore

The Supabase project is on the free plan, which has no backups. Instead,
`.github/workflows/db-backup.yml` runs every Saturday at 01:00 UTC. It dumps
the database, encrypts the copy with an `age` public key, and keeps it as a
workflow artifact for 90 days. Only the holder of the matching private key
can read a backup. The private key is never stored on GitHub.

## One-time setup

1. Create the key pair on your own computer:
   ```bash
   brew install age
   age-keygen -o ~/jobapply-backup-key.txt
   ```
   The command prints `Public key: age1...`.
2. Store the whole of `~/jobapply-backup-key.txt` in a password manager, then
   delete the file. **If this key is lost, every backup is unreadable.**
3. On GitHub, go to Settings → Secrets and variables → Actions → **Variables**.
   Add a variable named `BACKUP_AGE_RECIPIENT` whose value is the `age1...`
   public key.
4. Go to Actions → "Weekly database backup" → **Run workflow**. Check that the
   run is green and that an artifact named `jobapply-db-<date>` appears.

The workflow reads the `DATABASE_URL` secret that the LinkedIn scraper
workflow already uses.

## What a backup contains

- `app.dump` holds the `public` and `linkedin` schemas: profiles, CVs, jobs,
  applications and chats.
- `auth.dump` holds the rows of `auth.users` and `auth.identities`. Without
  them nobody can sign in to a restored database.

## Restore

Restore into a **new, empty** Supabase project first. Never restore straight
over production.

1. Download the artifact from the workflow run (Actions → the run →
   Artifacts) and unzip it.
2. Save the private key from your password manager to `key.txt`, then:
   ```bash
   age -d -i key.txt jobapply-db-<date>.tar.age | tar -xf -
   rm key.txt
   ```
3. Take the new project's session-pooler connection string, port 5432, as
   `$NEW_DB` and run:
   ```bash
   pg_restore --no-owner --no-privileges -d "$NEW_DB" app.dump
   pg_restore --data-only --disable-triggers -d "$NEW_DB" auth.dump
   ```
   Use `pg_restore` 17 (`brew install postgresql@17`).
4. Point `DATABASE_URL`, `SUPABASE_URL`, the JWT settings and the frontend's
   Supabase keys at the new project. Then sign in and check that your own
   data is there.
