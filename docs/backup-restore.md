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

## Test a restore locally

Run this every few months, and after any change to the backup workflow, so a
real restore is not the first one. It uses a throwaway Postgres on your own
computer and never touches Supabase. First tested 2026-11-23: all 28 tables,
18 users and 42 RLS policies came back.

1. Install PostgreSQL 17. `pg_restore` 16 cannot read a dump made by
   `pg_dump` 17. On an Intel Mac, Homebrew builds it from source, which takes
   about an hour.
   ```bash
   brew install postgresql@17
   ```
2. Download and decrypt the backup as in steps 1–2 of **Restore** above.
   Work in a folder outside the repo, such as `~/jobapply-restore-test`: once
   decrypted, the files hold real user data. A copied command overwrites the
   clipboard, so copy the key last, just before you press Enter.
3. Start a temporary server, listening only on a socket in that folder (not
   on the network). Without `LC_ALL`, Postgres on macOS stops with
   "postmaster became multithreaded during startup".
   ```bash
   export LC_ALL=en_US.UTF-8 P=/usr/local/opt/postgresql@17/bin D=$PWD
   $P/initdb -D pgdata -U postgres --auth=trust -E UTF8 --locale=C
   $P/pg_ctl -D pgdata -l pg.log -o "-p 5499 -k $D -c listen_addresses=''" -w start
   $P/psql -h $D -p 5499 -U postgres -d postgres -c "CREATE DATABASE restore_test"
   ```
4. Create the auth tables, then load the users, then the app. The repo path
   below is wherever your checkout lives.
   ```bash
   $P/psql -h $D -p 5499 -U postgres -d restore_test -f <repo>/backend/scripts/restore-auth-stub.sql
   $P/pg_restore -h $D -p 5499 -U postgres -d restore_test --data-only auth.dump
   $P/pg_restore -h $D -p 5499 -U postgres -d restore_test --no-owner --no-privileges app.dump
   ```
   The only expected error is `schema "public" already exists`.
5. Check that the data is there. Every profile should have a matching user:
   ```bash
   $P/psql -h $D -p 5499 -U postgres -d restore_test -c "SELECT (SELECT count(*) FROM auth.users) AS users, (SELECT count(*) FROM public.profiles) AS profiles, (SELECT count(*) FROM public.profiles p JOIN auth.users u ON u.id = p.id) AS linked"
   ```
6. Stop the server and delete everything that was decrypted:
   ```bash
   $P/pg_ctl -D pgdata -m fast stop
   rm -rf pgdata app.dump auth.dump pg.log
   ```
