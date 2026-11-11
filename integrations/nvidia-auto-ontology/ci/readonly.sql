-- Disposable DB CI experiment only. Never use on a production database.
-- psql variables: project_id and role_password.
\set ON_ERROR_STOP on
BEGIN;
DO $guard$ BEGIN
 IF current_database() <> 'sion_nvidia_ci' THEN
  RAISE EXCEPTION 'CI read-only pilot requires sion_nvidia_ci';
 END IF;
END $guard$;
REVOKE CONNECT ON DATABASE sion_nvidia_ci FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
CREATE ROLE nvidia_pilot_reader LOGIN PASSWORD :'role_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE nvidia_pilot_reader SET default_transaction_read_only = on;
ALTER ROLE nvidia_pilot_reader SET statement_timeout = '5000ms';
ALTER ROLE nvidia_pilot_reader CONNECTION LIMIT 4;
GRANT CONNECT ON DATABASE sion_nvidia_ci TO nvidia_pilot_reader;
CREATE SCHEMA sion_nv_pilot;
REVOKE ALL ON SCHEMA sion_nv_pilot FROM PUBLIC;
-- The authorized project UUID is compiled into the view, not set by the reader.
-- Intentionally do not expose properties, source_uri, documents, or raw evidence.
CREATE VIEW sion_nv_pilot.verified_project_objects WITH (security_barrier=true) AS
 SELECT e.id AS object_id,e.name AS object_name,e.entity_type_id AS object_type,
        p.id AS project_id,r.relation_type_id AS relationship_type
 FROM public.entities e
 JOIN public.relations r ON r.source_entity_id=e.id
 JOIN public.entities p ON p.id=r.target_entity_id
 WHERE p.id=:'project_id'::uuid
   AND p.entity_type_id='Project' AND e.entity_type_id='Concept'
   AND r.relation_type_id='PART_OF'
   AND r.verification_state='human_verified'
   AND (r.valid_from IS NULL OR r.valid_from<=CURRENT_TIMESTAMP)
   AND (r.valid_to IS NULL OR r.valid_to>CURRENT_TIMESTAMP)
   AND EXISTS(SELECT 1 FROM public.evidence ev
              WHERE ev.relation_id=r.id AND ev.verification_state='human_verified');
GRANT USAGE ON SCHEMA sion_nv_pilot TO nvidia_pilot_reader;
GRANT SELECT ON sion_nv_pilot.verified_project_objects TO nvidia_pilot_reader;
COMMIT;
