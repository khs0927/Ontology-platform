import os

# Test suite intentionally opts into local insecure write mode.
os.environ.setdefault("ONTOLOGY_SECURITY_MODE", "disabled")
