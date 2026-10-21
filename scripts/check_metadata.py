"""Validate prepared registry metadata against the vendored official schema."""

import hashlib
import json
import runpy
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
version = runpy.run_path(str(ROOT / "mcp_sequential_thinking/_version.py"))["__version__"]
server = json.loads((ROOT / "server.json").read_text())
schema_path = ROOT / "schemas/registry-server-2025-12-11.json"
schema = json.loads(schema_path.read_text())
Draft202012Validator.check_schema(schema)
Draft202012Validator(schema).validate(server)
assert server["version"] == server["packages"][0]["version"] == version
assert server["name"] == "io.github.arben-adm/mcp-sequential-thinking"
assert "mcp-name: " + server["name"] in (ROOT / "README.md").read_text()
print(
    json.dumps(
        {
            "registry_schema": server["$schema"],
            "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
            "version": version,
            "validation": "passed",
        }
    )
)
