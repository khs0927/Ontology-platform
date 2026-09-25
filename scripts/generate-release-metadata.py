#!/usr/bin/env python3
"""Generate deterministic, unsigned release supply-chain metadata.

Only artifact display names, release-relative identities, SHA-256 digests, and
sizes are copied into the release metadata. The generator never records input
directories, credentials, environment values, or claims that an artifact has
been signed or verified.

Publication model
-----------------
The whole metadata set (release-metadata.json, provenance.json, SHA256SUMS
and, when requested, sbom.json) is built inside a private staging directory
next to the output directory. Inputs are rehashed after the staging writes and
again after the commit; a change on either recheck aborts the run and restores
the previously published set, so a failed run never leaves a half-written or
stale metadata set behind.

Artifact identity
-----------------
A basename alone is not an identity: two different release inputs can share
one. Every record therefore carries a relative_name (the release-relative
location, when the artifact lives under the release root) plus an identity of
the form <sha256>/<relative-or-display-name>, and basename collisions between
distinct inputs are rejected instead of being silently overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "1.1"
METADATA_NAME = "release-metadata.json"
PROVENANCE_NAME = "provenance.json"
SUMS_NAME = "SHA256SUMS"
SBOM_NAME = "sbom.json"


class ReleaseMetadataError(RuntimeError):
    """Fail-closed condition: this run publishes nothing."""


def sha256(path):
    """Return the SHA-256 hex digest of a file, read in 1 MiB blocks."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def relative_name(root, path):
    """Return the release-relative POSIX name, or None when outside the root.

    Absolute input locations are never serialized; an artifact that lives
    outside the release root simply has no relative identity.
    """
    try:
        return Path(path).relative_to(Path(root)).as_posix()
    except ValueError:
        return None


def _inspect_input(p):
    """Refuse symlinks and anything that is not a regular file."""
    if Path(p).is_symlink():
        raise ReleaseMetadataError(
            "refusing symlink artifact input: " + Path(p).name +
            " (resolve it to a regular file before generating metadata)")
    if not Path(p).is_file():
        raise ReleaseMetadataError(
            "artifact input is not a regular file: " + Path(p).name)


def _observe(p):
    """Hash and size one artifact, refusing symlinks at read time too."""
    _inspect_input(p)
    return sha256(p), Path(p).stat().st_size


def snapshot_inputs(root, paths):
    """Observe every input once and derive its serializable record.

    Raises on an empty set, on symlinks and non-regular files, and on two
    distinct inputs that share a basename, because a basename is not a safe
    artifact identity.
    """
    paths = [Path(p) for p in paths]
    if not paths:
        raise ReleaseMetadataError(
            "refusing to generate metadata for an empty artifact set; "
            "supply at least one regular file via --artifact")
    seen_paths = set()
    by_basename = {}
    observed = []
    for p in paths:
        _inspect_input(p)
        if p in seen_paths:
            continue  # the same file listed twice is one artifact, not a clash
        seen_paths.add(p)
        digest, size = _observe(p)
        rel = relative_name(root, p)
        record = {"name": p.name, "sha256": digest, "size": size}
        if rel is not None:
            record["relative_name"] = rel
        record["identity"] = f"{digest}/{rel or p.name}"
        clash = by_basename.get(p.name)
        if clash is not None and clash["identity"] != record["identity"]:
            raise ReleaseMetadataError(
                f"artifact basename collision: {p.name!r} resolves to two distinct "
                f"inputs ({clash['identity']} and {record['identity']}); "
                "basenames alone are not a safe artifact identity")
        by_basename[p.name] = record
        observed.append((p, record))
    observed.sort(key=lambda item: str(item[1]["identity"]))
    return observed


def recheck(observed, phase):
    """Fail closed when any input no longer matches what the metadata claims."""
    for p, record in observed:
        if _observe(p) != (record["sha256"], record["size"]):
            raise ReleaseMetadataError(
                f"artifact changed {phase} metadata generation: {record['name']}")


def sbom(root, out):
    """Return the available SBOM tool name, or None when unavailable."""
    commands = (
        ["cyclonedx-py", "output", "--output-format", "json", "-o", str(out)],
        ["syft", "dir", str(root), "-o", "cyclonedx-json", "--file", str(out)],
    )
    for command in commands:
        if not shutil.which(command[0]):
            continue
        try:
            subprocess.run(command, cwd=root, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if out.is_file():
                return command[0]
        except (OSError, subprocess.CalledProcessError):
            pass
    return None


def _fsync_dir(path):
    """Make a directory entry durable where the platform supports it."""
    try:
        dir_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, AttributeError):
        pass


def _write_durable(path, text):
    """Write one staged file and flush it to stable storage."""
    with Path(path).open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def atomic_write(path, text):
    """Write durably and replace one destination file atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        _write_durable(tmp, text)
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()
    return sha256(path)


def safe_output(root, name):
    """Resolve a fixed output name inside root, rejecting traversal."""
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    p = (root / name).resolve()
    if p.parent != root:
        raise ValueError(f"output path escapes output directory: {name}")
    return p


def _staging_dir(output_dir):
    """Return a private, same-parent staging directory for the whole set."""
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    return parent / f".{output_dir.name}.staging-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _build_staged_set(staging, records, data, root, sbom_requested):
    """Write the complete metadata set into the private staging directory."""
    staging.mkdir(parents=True)
    if sbom_requested:
        tool = sbom(root, staging / SBOM_NAME)
        if tool:
            data["sbom"] = {"status": "generated", "generator": tool,
                            "sha256": sha256(staging / SBOM_NAME)}
        else:
            data["sbom"] = {"status": "blocked",
                            "blocker": "cyclonedx-bom and syft executables are not available"}
            (staging / SBOM_NAME).unlink(missing_ok=True)
    metadata_text = json.dumps(data, sort_keys=True, indent=2) + "\n"
    _write_durable(staging / METADATA_NAME, metadata_text)
    provenance = {
        "schema_version": SCHEMA_VERSION,
        "generator": "scripts/generate-release-metadata.py",
        "signature_status": "not_signed",
        "verified": False,
        "artifact_count": data["artifact_count"],
        "metadata_sha256": hashlib.sha256(metadata_text.encode("utf-8")).hexdigest(),
    }
    if "sbom" in data:
        provenance["sbom"] = data["sbom"]
    _write_durable(staging / PROVENANCE_NAME,
                   json.dumps(provenance, sort_keys=True, indent=2) + "\n")
    _write_durable(staging / SUMS_NAME, "".join(
        f"{r['sha256']}  {r.get('relative_name') or r['name']}\n" for r in records))
    _fsync_dir(staging)


def _publish(staging, output_dir):
    """Swap the staged set in as the published set.

    Returns the displaced previous set, if any, so a failing post-commit
    recheck can restore it. Renaming the staging directory is the single
    point at which the complete new set becomes visible.
    """
    backup = None
    if output_dir.exists():
        backup = output_dir.parent / (
            f".{output_dir.name}.previous-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        os.replace(output_dir, backup)
    try:
        os.replace(staging, output_dir)
    except OSError:
        if backup is not None:
            os.replace(backup, output_dir)
        raise
    _fsync_dir(output_dir.parent)
    return backup


def _discard(path):
    """Remove a staging or backup directory if it is still there."""
    if path is not None and path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _previous_set_is_current(backup, observed):
    """Report whether a displaced set still describes the inputs on disk.

    Restoring a set that no longer matches the artifacts would republish
    stale metadata, which is the one outcome a failed run must not produce.
    """
    try:
        records = json.loads((backup / METADATA_NAME).read_text(encoding="utf-8"))["artifacts"]
        current = {p.name: _observe(p) for p, _ in observed}
    except (OSError, ValueError, KeyError, TypeError, ReleaseMetadataError):
        return False
    return all(
        record.get("name") not in current
        or current[record["name"]] == (record.get("sha256"), record.get("size"))
        for record in records
    )


def generate(root, output_dir, artifacts, *, dry_run=False, sbom_requested=False):
    """Build the full metadata set and publish it atomically.

    Nothing is published unless every input still hashes to the recorded
    digest both before and after the commit.
    """
    root = Path(root).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    inputs = []
    for raw in artifacts:
        p = Path(raw).expanduser()
        _inspect_input(p)
        inputs.append(p.resolve())
    for p in inputs:
        if p == output_dir or output_dir in p.parents:
            raise ReleaseMetadataError(
                f"artifact lives inside the output directory: {p.name} "
                "(the metadata set would describe itself)")
    observed = snapshot_inputs(root, inputs)
    records = [record for _, record in observed]
    data = {
        "schema_version": SCHEMA_VERSION,
        "artifacts": records,
        "artifact_count": len(records),
        "signature_status": "not_signed",
        "verified": False,
    }
    if sbom_requested:
        data["sbom"] = {"status": "pending"}
    if dry_run:
        recheck(observed, "before")
        return data
    staging = _staging_dir(output_dir)
    backup = None
    published = False
    try:
        _build_staged_set(staging, records, data, root, sbom_requested)
        # Post-write recheck: the metadata must describe the bytes that are
        # still on disk, not a pre-write observation.
        recheck(observed, "during")
        backup = _publish(staging, output_dir)
        published = True
        recheck(observed, "after")
    except BaseException:
        if published:
            # What is live right now is stale: drop it, and only put the
            # previous set back when that set still matches the inputs.
            _discard(output_dir)
            if backup is not None:
                if _previous_set_is_current(backup, observed):
                    os.replace(backup, output_dir)
                else:
                    _discard(backup)
                backup = None
            _fsync_dir(output_dir.parent)
        _discard(staging)
        raise
    _discard(backup)
    return data


def main():
    """CLI entry point; fail-closed conditions exit with status 2."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--artifact", type=Path, action="append", default=[])
    p.add_argument("--sbom", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    try:
        result = generate(a.root.resolve(), a.output_dir, a.artifact,
                          dry_run=a.dry_run, sbom_requested=a.sbom)
    except (ReleaseMetadataError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
