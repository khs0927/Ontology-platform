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
