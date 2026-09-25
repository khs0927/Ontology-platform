# Release supply-chain metadata

## Release dependency lock

`requirements-release.lock` is the canonical release input for this branch. It
contains fully-qualified `==` pins and a SHA-256 digest for every direct
runtime, test, build, packaging, and vector client requirement. `httpx2` and
`PyYAML` are test-only; `pgvector` is the Python client for PostgreSQL's
server-side `vector` extension and supplies the SQLAlchemy `Vector`/`vector`
type support. PyInstaller and setuptools are build requirements.

Run the fail-closed verifier before building or publishing:

```powershell
python scripts/verify-release-lock.py
```

## Metadata generation

`scripts/generate-release-metadata.py` reads explicitly supplied artifacts and
writes `release-metadata.json`, `SHA256SUMS`, and `provenance.json` without
modifying the artifacts. Output names are restricted to the requested output
directory and traversal is rejected:

```powershell
python scripts/generate-release-metadata.py --output-dir dist/metadata `
  --artifact dist/sion_ontology_platform-0.1.0-py3-none-any.whl `
  --artifact dist/sion_ontology_platform-0.1.0.tar.gz `
  --dry-run
```

Release metadata contains only artifact `name`, `sha256`, and `size` records,
plus `relative_name` and `identity`, the schema/version, count, and explicit
release status. It never records absolute input paths, credentials,
environment values, or other private paths.

## Artifact identity

A basename is a label, not an identity: two release inputs can share one
(`dist/a/demo-1.0.whl` and `dist/b/demo-1.0.whl`). Each record therefore also
carries:

- `relative_name`: the path relative to the release root, in POSIX form. It is
  omitted when the artifact lives outside the root, so no absolute location is
  ever serialized.
- `identity`: `<sha256>/<relative_name or name>`, unique per distinct input.

Records are sorted by `identity`, so ordering does not depend on argument order
or on the filesystem. Two distinct inputs sharing a basename are a collision
and the run fails instead of letting one silently overwrite the other in
`SHA256SUMS`. The same file listed twice is one artifact, not a collision.
`SHA256SUMS` lines use `relative_name` where available, so the sums file stays
unambiguous for multi-file releases.

## Publication is atomic as a set

`release-metadata.json`, `provenance.json`, `SHA256SUMS` and the optional
`sbom.json` are written together into a private staging directory next to the
output directory. Each file is `fsync`ed, the staging directory is `fsync`ed,
and only then is the whole directory renamed into place. The rename is the
single point at which the complete set becomes visible, so a reader never sees
a new `SHA256SUMS` beside an old `release-metadata.json`, and an unrelated file
left in the output directory is not carried into the new set.

Inputs are rehashed twice: after the staging writes and again after the
commit. A change at either point aborts the run:

- Before the commit, nothing is published and the staging directory is
  removed.
- After the commit, the new set is dropped and the previous set is restored,
  but only when that previous set still matches the inputs on disk. If it does
  not, the output directory is left empty rather than republishing stale
  metadata.

A failed run therefore leaves no staging or backup directories behind. The
residual window between "old set moved aside" and "new set renamed in" is two
renames in the same parent directory; a crash there leaves the previous set
under its `.previous-` name for the operator to inspect, not a mixed set.

## Fail-closed inputs

- Symlink inputs are rejected, at the initial read and at every recheck, so a
  link cannot be swapped in between hashing and commit.
- An empty artifact set is refused: no `--artifact` means no release metadata.
- Inputs that are missing or not regular files are refused rather than skipped,
  so a typo cannot silently produce metadata for a smaller release.
- An artifact located inside the output directory is refused, because the
  metadata set would then describe itself.
- Refused conditions exit with status 2 and a message on stderr; the CLI never
  prints a success payload for a run that published nothing.

## Not a signature

The generator does not sign artifacts. Every result explicitly records
`signature_status: not_signed` and `verified: false`; it must not be described
as signed or as verified provenance. `provenance.json` is a record of what was
hashed, nothing more. `--dry-run` performs the read-only metadata calculation
and writes no files.

## SBOM interoperability

`--sbom` tries `cyclonedx-py` and then `syft`, producing CycloneDX JSON when a
tool is available. If neither tool is installed, metadata records `status:
blocked` with the unavailable-tools blocker, no `sbom.json` is written, and the
generator does not fabricate components.
The SBOM, dependency lock, and build environment still require review before
publication.
