-- Enable required PostgreSQL extensions
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Create app user (non-superuser)
CREATE USER hrms_app WITH PASSWORD 'hrms_app_password';

-- Grant permissions
GRANT CONNECT ON DATABASE hrms_db TO hrms_app;
GRANT USAGE ON SCHEMA public TO hrms_app;

-- Grant permissions on existing tables (if any)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hrms_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hrms_app;

-- Alter default privileges for future tables created by migrations
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hrms_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO hrms_app;
