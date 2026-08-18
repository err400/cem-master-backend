-- Runs once, on first initialisation of the Postgres data volume.
--
-- Creates the throwaway database the test suite points TEST_DATABASE_URL at, so
-- `pytest` works immediately after `./scripts/dev-up.sh` without a manual
-- createdb step.
--
-- NOTE: this only executes when the volume is empty. If you add something here
-- later, recreate the volume to pick it up:
--     ./scripts/dev-up.sh down -v && ./scripts/dev-up.sh

CREATE DATABASE cem_master_test;

-- pg_trgm powers the species-name search indexes in docs/postgres-indexes.sql.
-- Created here as well as in the application database because tests that build
-- the schema from scratch need it present.
\connect cem_master_test
CREATE EXTENSION IF NOT EXISTS pg_trgm;

\connect cem_master
CREATE EXTENSION IF NOT EXISTS pg_trgm;
