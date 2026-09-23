# Ontology and database mapping

The LinkML schema is the interchange vocabulary. The API/database schema uses
relational names and JSON values where those represent the same concept.

| Concept | LinkML / flat interchange | API / database |
| --- | --- | --- |
| Relation source | `source_id` | `source_entity_id` |
| Relation target | `target_id` | `target_entity_id` |
| Relation type | `relation_type` | `relation_type_id` |
| Properties | JSON serialized as a string in flat LinkML interchange | JSON object in API and JSONB in PostgreSQL |
| Artifact identity | `Artifact` is an `Entity` | `artifacts.entity_id` may reference `entities.id`; older artifact metadata remains standalone |
| Dataset / Deliverable | Entity subtypes | an `Artifact`, `Dataset` or `Deliverable` entity may back one artifact metadata row |

Map import/export code is the conversion boundary for the external map format.
IDs are retained where possible; source node and relation IDs are carried in
`properties.map_source_id` when they are namespaced into stable database keys.

When creating a graph backed artifact, first create an Entity of type
`Artifact`, `Dataset`, or `Deliverable`, then POST the artifact metadata with
that Entity's `id` in `entity_id`. Standalone artifact metadata from earlier
versions is still supported. Existing standalone rows do not automatically
appear in `/graph` until they are linked to an Entity.

The `sion:` prefix and current ontology IRI are retained as the stable legacy
namespace for this schema version. Changing them requires an explicit ontology
version and IRI migration because external RDF references may depend on them.

## Isolated local PostgreSQL

To avoid colliding with another checkout running the development database:

```sh
COMPOSE_PROJECT_NAME=ontology-platform-sandbox ONTOLOGY_PG_PORT=5543 ./scripts/dev_postgres.sh up
```

The Compose project name gives its volume a separate namespace, and the host
port can be changed independently. The default remains `ontology-platform` on
port `5433` for existing local workflows.
