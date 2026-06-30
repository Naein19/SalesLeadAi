-- 1. Ensure crmsyncstate enum has 'syncing' and 'retrying' values
-- Note: ALTER TYPE cannot be run inside a transaction block in Postgres.
ALTER TYPE crmsyncstate ADD VALUE IF NOT EXISTS 'syncing';
ALTER TYPE crmsyncstate ADD VALUE IF NOT EXISTS 'retrying';

-- 2. Add defaults to jobs table columns to match ORM defaults
ALTER TABLE jobs ALTER COLUMN total SET DEFAULT 0;
ALTER TABLE jobs ALTER COLUMN completed SET DEFAULT 0;
ALTER TABLE jobs ALTER COLUMN failed SET DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS running INTEGER DEFAULT 0;
ALTER TABLE jobs ALTER COLUMN running SET DEFAULT 0;
ALTER TABLE jobs ALTER COLUMN status SET DEFAULT 'queued';

-- Backfill existing NULLs in jobs table for these fields
UPDATE jobs SET total = 0 WHERE total IS NULL;
UPDATE jobs SET completed = 0 WHERE completed IS NULL;
UPDATE jobs SET failed = 0 WHERE failed IS NULL;
UPDATE jobs SET running = 0 WHERE running IS NULL;
UPDATE jobs SET status = 'queued' WHERE status IS NULL;

-- Enforce NOT NULL constraints on jobs columns
ALTER TABLE jobs ALTER COLUMN total SET NOT NULL;
ALTER TABLE jobs ALTER COLUMN completed SET NOT NULL;
ALTER TABLE jobs ALTER COLUMN failed SET NOT NULL;
ALTER TABLE jobs ALTER COLUMN running SET NOT NULL;

-- 3. Add defaults and NOT NULL constraints to uploads table
ALTER TABLE uploads ALTER COLUMN records_count SET DEFAULT 0;
UPDATE uploads SET records_count = 0 WHERE records_count IS NULL;
ALTER TABLE uploads ALTER COLUMN records_count SET NOT NULL;

ALTER TABLE uploads ALTER COLUMN status SET DEFAULT 'queued';
UPDATE uploads SET status = 'queued' WHERE status IS NULL;
ALTER TABLE uploads ALTER COLUMN status SET NOT NULL;

-- 4. Align leads table constraints with ORM models
ALTER TABLE leads ALTER COLUMN status SET DEFAULT 'pending';
ALTER TABLE leads ALTER COLUMN email SET DEFAULT '';

-- Align retry_count
ALTER TABLE leads ALTER COLUMN retry_count SET DEFAULT 0;
UPDATE leads SET retry_count = 0 WHERE retry_count IS NULL;
ALTER TABLE leads ALTER COLUMN retry_count SET NOT NULL;

-- Align timestamps
ALTER TABLE leads ALTER COLUMN created_at SET DEFAULT NOW();
UPDATE leads SET created_at = NOW() WHERE created_at IS NULL;
ALTER TABLE leads ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE leads ALTER COLUMN updated_at SET DEFAULT NOW();
UPDATE leads SET updated_at = NOW() WHERE updated_at IS NULL;
ALTER TABLE leads ALTER COLUMN updated_at SET NOT NULL;
