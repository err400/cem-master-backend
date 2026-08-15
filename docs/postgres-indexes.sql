-- Reference indexes for the separately managed cem-database service.
-- The database owner should review and apply these through their migration tool.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_species_common_name_trgm
    ON species USING gin (common_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_species_scientific_name_trgm
    ON species USING gin (scientific_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_spot_species_species_activity
    ON spot_species_summaries (species_id, detection_count DESC, spot_id);

CREATE INDEX IF NOT EXISTS ix_spot_species_spot_activity
    ON spot_species_summaries (spot_id, detection_count DESC, species_id);

CREATE INDEX IF NOT EXISTS ix_spot_species_migration
    ON spot_species_summaries (migration_class, spot_id, species_id);

CREATE INDEX IF NOT EXISTS ix_species_daily_date_spot
    ON spot_species_daily (species_id, observation_date, spot_id)
    WHERE detection_count > 0;

CREATE INDEX IF NOT EXISTS ix_spot_daily_species_date
    ON spot_species_daily (spot_id, species_id, observation_date)
    WHERE detection_count > 0;

CREATE INDEX IF NOT EXISTS ix_analysis_jobs_spot_species_started
    ON analysis_jobs (spot_id, species_id, started_at DESC);

CREATE INDEX IF NOT EXISTS ix_environment_spot_date
    ON spot_environment_daily (spot_id, observation_date);
