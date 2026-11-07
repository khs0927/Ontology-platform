"""Exercise the actual NVIDIA PostgreSQL connector against a synthetic Sion DB.

This script is launched from a SHA-pinned NVIDIA checkout in GitHub Actions.
No mock transport, customer data, LLM inference or deployed server.
"""
import os

import psycopg
from auto_ontology.connectors.registry import create_connector

DSN=os.environ["SION_NVIDIA_PILOT_RO_DSN"]
EXPECTED={("sion_nv_pilot","verified_project_objects")}

def deny(statement: str, why: str) -> None:
    try:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(statement).fetchall()
    except psycopg.Error as error:
        assert error.sqlstate in {"42501","25006","42P01","55000"}, (why,error.sqlstate)
        print(f"DENIED {why}: SQLSTATE {error.sqlstate}")
        return
    raise AssertionError(f"UNSAFE: {why} unexpectedly allowed")

def main() -> None:
    with psycopg.connect(DSN, autocommit=True) as conn:
        assert conn.execute("SELECT current_user").fetchone()[0]=="nvidia_pilot_reader"
        result=conn.execute(
            "SELECT object_name FROM sion_nv_pilot.verified_project_objects ORDER BY object_name"
        ).fetchall()
        assert [row[0] for row in result]==["Door-101","Door-102"],result
    with create_connector(DSN) as connector:
        tables=connector.get_tables()
        visible=set(zip(tables.table_schema.tolist(),tables.table_name.tolist()))
        assert visible==EXPECTED, f"NVIDIA metadata escaped project view: {visible}"
        columns=set(connector.get_columns().column_name.tolist())
        assert columns=={"object_id","object_name","object_type","project_id","relationship_type"},columns
        query=connector.execute("SELECT count(*) AS door_count FROM sion_nv_pilot.verified_project_objects")
        assert int(query.loc[0,"door_count"])==2,query
        # These are verified, deterministic SQL lookups, NOT model-generated SQL.
        # Compare raw PostgreSQL answers and the actual NVIDIA PostgresDatabase
        # connector on the same project-scoped view with expected gold answers.
        relation = "sion_nv_pilot.verified_project_objects"
        goldens = [
            ("approved-total", "SELECT count(*) FROM " + relation, 2),
            ("concept-objects", "SELECT count(*) FROM " + relation + " WHERE object_type='Concept'", 2),
            ("part-of", "SELECT count(*) FROM " + relation + " WHERE relationship_type='PART_OF'", 2),
            ("distinct-names", "SELECT count(DISTINCT object_name) FROM " + relation, 2),
            ("one-project", "SELECT count(DISTINCT project_id) FROM " + relation, 1),
            ("project-A", "SELECT count(*) FROM " + relation + " WHERE project_id='00000000-0000-0000-0000-0000000000a1'", 2),
            ("project-B-private", "SELECT count(*) FROM " + relation + " WHERE project_id='00000000-0000-0000-0000-0000000000b1'", 0),
            ("door-101", "SELECT count(*) FROM " + relation + " WHERE object_name='Door-101'", 1),
            ("door-102", "SELECT count(*) FROM " + relation + " WHERE object_name='Door-102'", 1),
            ("rejected-excluded", "SELECT count(*) FROM " + relation + " WHERE object_name='Door-Rejected'", 0),
            ("evidence-unverified", "SELECT count(*) FROM " + relation + " WHERE object_name='Door-No-Evidence'", 0),
            ("past-expired", "SELECT count(*) FROM " + relation + " WHERE object_name='Door-Expired'", 0),
            ("future-invalid", "SELECT count(*) FROM " + relation + " WHERE object_name='Door-Future'", 0),
            ("private-object", "SELECT count(*) FROM " + relation + " WHERE object_name='Project-B-Private-Door'", 0),
            ("matching-prefix", "SELECT count(*) FROM " + relation + " WHERE object_name LIKE 'Door-1%'", 2),
            ("filtered-aggregate", "SELECT count(*) FILTER(WHERE object_name='Door-101') FROM " + relation, 1),
        ]
        with psycopg.connect(DSN, autocommit=True) as raw:
            for label, sql, gold in goldens:
                expected_from_db = raw.execute(sql).fetchone()[0]
                result_from_nvidia = connector.execute(sql).iloc[0, 0]
                assert int(expected_from_db) == gold, (label, "raw", expected_from_db)
                assert int(result_from_nvidia) == gold, (label, "nvidia", result_from_nvidia)
        print(f"PASS: {len(goldens)}/{len(goldens)} deterministic SQL goldens via actual NVIDIA connector")
    for sql,reason in [
        ("SELECT * FROM public.entities","canonical entities"),
        ("SELECT * FROM public.relations","canonical relations"),
        ("SELECT * FROM public.evidence","canonical evidence"),
        ("UPDATE public.entities SET name='forbidden'","canonical UPDATE"),
        ("DELETE FROM public.relations","canonical DELETE"),
        ("UPDATE sion_nv_pilot.verified_project_objects SET object_name='forbidden'","view UPDATE"),
    ]:
        deny(sql,reason)
    print("PASS: real NVIDIA connector saw exactly one approved Sion view (2 rows)")

if __name__=="__main__":
    main()
