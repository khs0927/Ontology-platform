# Release supply-chain metadata

## Release dependency lock

`requirements-release.lock` is the canonical release input for this branch. It
contains fully-qualified `==` pins and a SHA-256 digest for every direct
runtime, test, build, packaging, and vector client requirement. `httpx2` and
`PyYAML` are test-only; `pgvector` is the Python client for PostgreSQL's
server-side `vector` extension and supplies the SQLAlchemy `Vector`/`vector`
type support (the extension itself is not a PyPI package).
PyInstaller and setuptools are build requirements and must not become runtime
requirements.

Run the fail-closed verifier before building or publishing:

```powershell
python scripts/verify-release-lock.py
```

It rejects missing entries, unlisted entries, version drift, non-exact pins,
malformed lines, and any line without a valid SHA-256 hash. Regenerate and
review the lock whenever `pyproject.toml` or the build contract changes.


`scripts/generate-release-metadata.py` creates release metadata without changing
any existing wheel, sdist, or EXE.  Pass each artifact explicitly:

```powershell
python scripts/generate-release-metadata.py --output-dir dist/metadata `
  --artifact dist/sion_ontology_platform-0.1.0-py3-none-any.whl `
  --artifact dist/sion_ontology_platform-0.1.0.tar.gz `
  --artifact dist/sion-agent-bridge.exe --sbom
```

The output contains `release-metadata.json`, `SHA256SUMS`, and unsigned
`provenance.json`; `--sbom` additionally creates `sbom.json` when a CycloneDX
or syft executable is available.  Metadata records Git SHA and dirty state,
Python and dependency versions, PyInstaller/build backend versions, Alembic head,
and hashes of packaged ontology/SHACL/resource files.  JSON keys are sorted and
no environment variable values are copied into output, making reruns
reproducible.  Filenames are written only below the requested output directory;
traversal paths are rejected.

This generator does **not** sign artifacts.  Every generated provenance record
therefore explicitly says `signature_status: not_signed` and `verified: false`.
It must not be described as signed or as verified provenance until a separate
trusted signing and verification process is added.

## SBOM interoperability

The optional SBOM path tries `cyclonedx-py` first and then `syft`, producing
CycloneDX JSON.  If neither tool is installed, the release metadata records the
SBOM as unavailable rather than fabricating components.  Review the resulting
SBOM and dependency lock/build environment before publication.
