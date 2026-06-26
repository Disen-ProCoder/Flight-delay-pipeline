-- ============================================================
-- sql/schema/01_create_database.sql
-- Run as postgres superuser:
--   psql -U postgres -f sql/schema/01_create_database.sql
-- ============================================================

-- Create dedicated pipeline user (don't use superuser for app)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pipeline_user') THEN
        CREATE ROLE pipeline_user WITH LOGIN PASSWORD 'change_this_password';
    END IF;
END
$$;

-- Create the warehouse database
CREATE DATABASE flight_warehouse
    OWNER = pipeline_user
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8'
    TEMPLATE = template0;

-- Create separate Airflow metadata database
CREATE DATABASE airflow_db
    OWNER = pipeline_user
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8'
    TEMPLATE = template0;

GRANT ALL PRIVILEGES ON DATABASE flight_warehouse TO pipeline_user;
GRANT ALL PRIVILEGES ON DATABASE airflow_db TO pipeline_user;
