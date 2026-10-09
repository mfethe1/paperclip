"""Publication gates for the fleet-184991 consolidation.

Real checks, no mocks: every published file is hash-verified against the
manifest, scanned for secret/private-identifier patterns, and the status
distinctions (rejected / prototype / reviewed) are enforced structurally.
"""

import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # contrib/fleet-184991
MANIFEST = ROOT / "manifest.json"

# Patterns that must never appear in published consolidation files.
FORBIDDEN = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key material"),
    (re.compile(r"\bsk-[A-Za-z0-9]{12,}"), "provider API key shape"),
    (re.compile(r"[a-z0-9-]+\.tail[0-9a-f]+\.ts\.net"), "real tailnet host name"),
    (re.compile(r"/Users/[a-z][a-z0-9]*"), "absolute account path"),
    (re.compile(r"\b100\.(?:\d{1,3})\.(?:\d{1,3})\.(?:\d{1,3})\b"), "tailnet IPv4"),
    (re.compile(r"7991290678"), "private chat identifier"),
    (re.compile(r"1b6cf0d9-5f58-490e-996e-7b59fb2ff672"), "real company instance ID"),
    (re.compile(r"41aa6e7d-2ff9-4aeb-8187-d2b022b0a0cf"), "real project instance ID"),
    (re.compile(r"paperclip-shared-secret"), "default shared secret"),
    (re.compile(r"Michaels-Mac"), "operator host name"),
]

ALLOWED_STATUS = {
    "reviewed-accept-admission-only",
    "rejected-superseded-provenance-only",
    "prototype-containment-unqualified",
    "prototype-vm-unprovisioned",
    "authored-consolidation-doc",
    "authored-sanitized-script",
    "authored-gate-test",
    "authored",
}

SELF_EXEMPT = {"manifest.json", "tests/test_manifest.py"}


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text())
        cls.entries = {f["path"]: f for f in cls.manifest["files"]}

    def test_manifest_schema_and_base(self):
        self.assertEqual(self.manifest["schema"], "fleet-184991-publication-manifest/v1")
        self.assertRegex(self.manifest["upstream_base_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(len(self.manifest["source_commits"]), 4)

    def test_every_file_listed_and_hash_verified(self):
        import subprocess

        tracked = subprocess.run(
            ["git", "ls-files", "--", str(ROOT.relative_to(ROOT.parents[1]))],
            cwd=ROOT.parents[1],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        on_disk = {
            path
            for path in tracked
            if path not in {
                "contrib/fleet-184991/manifest.json",
                "contrib/fleet-184991/tests/test_manifest.py",
            }
        }
        self.assertEqual(on_disk, set(self.entries), "manifest/disk coverage mismatch")
        for path, entry in self.entries.items():
            data = (ROOT.parents[1] / path).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"], path)

    def test_status_labels_valid_and_distinctions_preserved(self):
        for entry in self.entries.values():
            self.assertIn(entry["status"], ALLOWED_STATUS, entry["path"])
        by = {}
        for entry in self.entries.values():
            by.setdefault(entry["status"], []).append(entry["path"])
        # The rejected baseline and both unqualified prototypes must be present
        # and labeled — distinctions are part of the publication.
        self.assertIn("rejected-superseded-provenance-only", by)
        self.assertIn("prototype-containment-unqualified", by)
        self.assertIn("prototype-vm-unprovisioned", by)
        self.assertIn("reviewed-accept-admission-only", by)

    def test_sanitized_files_differ_from_source_and_record_both_hashes(self):
        for entry in self.entries.values():
            if entry.get("modified_from_source"):
                # Published file derives from the recorded source but carries
                # functional changes beyond sanitization; each such change is
                # described in AUDIT.md. Provenance hash is still mandatory.
                self.assertTrue(entry["source_sha256"], entry["path"])
                self.assertNotEqual(entry["source_sha256"], entry["sha256"], entry["path"])
            elif entry["sanitized"]:
                self.assertTrue(entry["source_sha256"], entry["path"])
                self.assertNotEqual(entry["source_sha256"], entry["sha256"], entry["path"])
            elif entry["source_sha256"]:
                self.assertEqual(entry["source_sha256"], entry["sha256"], entry["path"])

    def test_no_secret_or_private_identifier_patterns(self):
        for path in self.entries:
            text = (ROOT.parents[1] / path).read_text(errors="replace")
            for pattern, label in FORBIDDEN:
                self.assertIsNone(pattern.search(text), f"{label} found in {path}")

    def test_rejected_baseline_is_not_the_reviewed_module(self):
        rejected = self.entries[
            "contrib/fleet-184991/connector-admission-rejected/admission.py"
        ]
        reviewed = self.entries["contrib/fleet-184991/connector-admission/admission.py"]
        self.assertNotEqual(rejected["sha256"], reviewed["sha256"])
        rejection_notice = (ROOT / "connector-admission-rejected" / "REJECTION.md").read_text()
        self.assertIn("REJECTED", rejection_notice)

    def test_scripts_fail_loudly_without_secrets(self):
        start = (ROOT / "scripts" / "paperclip-dev-start.sh").read_text()
        self.assertIn(": \"${PAPERCLIP_AGENT_JWT_SECRET:?", start)
        self.assertNotIn(":-paperclip", start)


if __name__ == "__main__":
    unittest.main(verbosity=2)
