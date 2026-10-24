import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


router = module("router", REPO / "skills/skill-router/scripts/router.py")
installer = module("installer", REPO / "scripts/install.py")


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "skills"
        self.state = self.base / "state"
        self.create("animation", "Create mathematical animations with ManimGL.", "Render the scene and inspect the resulting frames.")
        self.create("pdf", "Inspect and create PDF documents.", "Inspect every rendered page before delivering the document.")

    def create(self, name, description, body, folder=None):
        path = self.root / (folder or name) / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: >-\n  {description}\n---\n\n{body}\n", encoding="utf-8")
        return path

    def start(self):
        catalog = router.build_index([self.root])
        run = router.begin(self.state, catalog, "Inspect a sample animation", ["animation::Create and inspect a math animation"])
        return catalog, run, run["skills"][0]

    def ready(self):
        catalog, run, entry = self.start()
        router.record_load(entry, "SKILL.md")
        router.acknowledge(entry, "SKILL.md", "Render the actual animation and inspect its frames.")
        criterion = router.add_criterion(entry, "SKILL.md", "Render the scene and inspect the resulting frames.", "The scene renders and frames show the intended shape.")
        artifact = self.base / "check.txt"
        artifact.write_text("Rendered 38 frames; first and last frames inspected.", encoding="utf-8")
        router.record_evidence(criterion, "pass", "Rendered successfully and inspected both endpoint frames.", artifact)
        return catalog, run, entry, criterion, artifact

    def test_index_metadata_is_not_a_load(self):
        catalog, run, entry = self.start()
        self.assertEqual(2, len(catalog["skills"]))
        self.assertFalse(router.verify(run)["verified"])
        self.assertEqual({}, entry["loads"])

    def test_hidden_system_directory_and_folded_yaml(self):
        self.create("system-helper", "A folded\n  multiline description.", "Use the correct tool.", ".system/helper")
        catalog = router.build_index([self.root])
        self.assertEqual(3, len(catalog["skills"]))
        self.assertEqual("A folded multiline description.", router.resolve(catalog["skills"], "system-helper")["description"])

    def test_malformed_skill_is_reported(self):
        self.create("bad", "A description", "Body").write_text("no frontmatter")
        catalog = router.build_index([self.root])
        self.assertEqual(1, len(catalog["errors"]))
        self.assertEqual(2, len(catalog["skills"]))

    def test_missing_root_is_reported(self):
        catalog = router.build_index([self.root, self.base / "missing"])
        self.assertEqual(1, len(catalog["errors"]))

    def test_duplicate_names_require_ids(self):
        self.create("pdf", "Other PDF helper.", "Check the pages.", "other-pdf")
        catalog = router.build_index([self.root])
        with self.assertRaises(router.RouterError): router.resolve(catalog["skills"], "pdf")
        matches = [s for s in catalog["skills"] if s["name"] == "pdf"]
        self.assertNotEqual(matches[0]["id"], matches[1]["id"])
        self.assertEqual(matches[0], router.resolve(catalog["skills"], matches[0]["id"]))

    def test_overlapping_roots_deduplicate_paths(self):
        self.assertEqual(2, len(router.build_index([self.root, self.root / "pdf"])["skills"]))

    def test_explicit_only_policy(self):
        folder = self.root / "pdf" / "agents"
        folder.mkdir()
        (folder / "openai.yaml").write_text("policy:\n  allow_implicit_invocation: false\n")
        entries = router.build_index([self.root])["skills"]
        self.assertEqual([], router.rank(entries, "PDF documents"))
        self.assertEqual("pdf", router.rank(entries, "anything", required=["pdf"])[0]["name"])

    def test_ranking_explains_and_excludes(self):
        entries = router.build_index([self.root])["skills"]
        candidates = router.rank(entries, "ManimGL animations")
        self.assertEqual("animation", candidates[0]["name"])
        self.assertIn("manimgl", candidates[0]["matched_terms"])
        self.assertEqual([], router.rank(entries, "ManimGL", excluded=["animation"]))
        with self.assertRaises(router.RouterError): router.rank(entries, "PDF", ["pdf"], ["pdf"])

    def test_required_skills_are_not_truncated(self):
        entries = router.build_index([self.root])["skills"]
        self.assertEqual(2, len(router.rank(entries, "irrelevant", ["animation", "pdf"], limit=1)))

    def test_stale_catalog_prevents_new_run(self):
        catalog = router.build_index([self.root])
        with (self.root / "animation/SKILL.md").open("a") as file: file.write("Changed instruction.")
        with self.assertRaises(router.RouterError): router.begin(self.state, catalog, "Task", ["animation::Read the new instruction"])

    def test_unacknowledged_load_cannot_define_contract(self):
        _, run, entry = self.start()
        router.record_load(entry, "SKILL.md")
        with self.assertRaises(router.RouterError): router.add_criterion(entry, "SKILL.md", "Render the scene", "Check the final output")
        self.assertFalse(router.verify(run)["verified"])

    def test_nonexistent_quote_is_rejected(self):
        _, _, entry = self.start()
        router.record_load(entry, "SKILL.md")
        router.acknowledge(entry, "SKILL.md", "Use the scene rendering requirement.")
        with self.assertRaises(router.RouterError): router.add_criterion(entry, "SKILL.md", "Invented requirement here", "Check a final artifact")

    def test_successful_contract_has_reviewable_evidence(self):
        _, run, _, criterion, artifact = self.ready()
        self.assertTrue(router.verify(run)["verified"])
        self.assertEqual(router.file_hash(artifact), criterion["evidence"]["artifact"]["sha256"])

    def test_failed_and_blocked_evidence_never_passes(self):
        _, run, _, criterion, _ = self.ready()
        for status in ("fail", "blocked"):
            router.record_evidence(criterion, status, "The required rendering check did not succeed.")
            self.assertFalse(router.verify(run)["verified"])
        self.assertEqual(3, len(criterion["history"]))

    def test_evidence_mutation_is_detected(self):
        _, run, _, _, artifact = self.ready()
        artifact.write_text("Different evidence")
        self.assertFalse(router.verify(run)["verified"])

    def test_stale_sources_need_new_contract_and_evidence(self):
        _, run, entry, criterion, _ = self.ready()
        path = Path(entry["path"])
        path.write_text(path.read_text() + "\nA new material condition.\n")
        self.assertFalse(router.verify(run)["verified"])
        router.record_load(entry, "SKILL.md")
        router.acknowledge(entry, "SKILL.md", "The new condition is incorporated into the artifact check.")
        self.assertFalse(router.verify(run)["verified"])
        updated = router.add_criterion(entry, "SKILL.md", criterion["quote"], "Check rendered frames and the new condition.", criterion["id"], "The source now adds a material condition.")
        self.assertIn("supersedes", updated)
        self.assertFalse(router.verify(run)["verified"])
        router.record_evidence(updated, "pass", "Rechecked the rendering and the newly stated condition.")
        self.assertTrue(router.verify(run)["verified"])

    def test_resource_escape_and_run_traversal_rejected(self):
        _, _, entry = self.start()
        with self.assertRaises(router.RouterError): router.resource(entry, "../pdf/SKILL.md")
        with self.assertRaises(router.RouterError): router.run_path(self.state, "../../catalog")

    def test_symlink_escape_rejected(self):
        _, _, entry = self.start()
        link = self.root / "animation" / "outside.md"
        try: link.symlink_to(self.root / "pdf/SKILL.md")
        except OSError: self.skipTest("Symlink creation not available")
        with self.assertRaises(router.RouterError): router.resource(entry, "outside.md")

    def test_coverage_does_not_count_stale_passes(self):
        catalog, run, entry, _, artifact = self.ready()
        run["status"] = "verified"
        rows = router.coverage(catalog, [run])
        self.assertEqual(1, next(r for r in rows if r["name"] == "animation")["verified_runs"])
        artifact.unlink()
        self.assertEqual(0, next(r for r in router.coverage(catalog, [run]) if r["name"] == "animation")["verified_runs"])

    def test_cli_exit_codes_and_persistence(self):
        def call(*args):
            output = io.StringIO()
            with contextlib.redirect_stdout(output): code = router.main(["--state", str(self.state), *args])
            return code, output.getvalue()
        self.assertEqual(0, call("index", "--root", str(self.root))[0])
        code, out = call("begin", "--task", "Short local label", "--select", "animation::Verify the scene")
        run_id = json.loads(out)["run"]
        self.assertEqual(1, call("verify", run_id)[0])
        self.assertEqual(0, call("load", run_id, "animation")[0])
        self.assertIn("Render the scene", call("load", run_id, "animation")[1])
        self.assertEqual("in-progress", router.read_json(router.run_path(self.state, run_id))["status"])

    def test_cli_preserves_unicode_in_legacy_terminal(self):
        content = "Inspect naïve → 中文 🧭 labels without changing their text."
        self.create("unicode", "Inspect multilingual labels.", content)
        def call(*args):
            result = subprocess.run(
                [sys.executable, str(REPO / "skills/skill-router/scripts/router.py"),
                 "--state", str(self.state), *args], capture_output=True,
                env={**os.environ, "PYTHONIOENCODING": "ascii"}, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
            return result.stdout.decode("utf-8")
        call("index", "--root", str(self.root))
        run_id = json.loads(call("begin", "--task", "Unicode output", "--select", "unicode::Inspect labels"))["run"]
        self.assertIn(content, call("load", run_id, "unicode"))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.source = REPO / "skills/skill-router"
        self.find = self.home / "skills/find-skills/SKILL.md"
        self.find.parent.mkdir(parents=True)
        self.find.write_bytes(b"---\r\nname: find-skills\r\n---\r\nOriginal instructions.\r\n")
        (self.home / "AGENTS.md").write_text("Keep this user preference.\n")

    def test_install_preserves_and_backs_up_originals(self):
        original = self.find.read_bytes()
        result = installer.install(self.source, self.home, True, True)
        self.assertIn("Original instructions.", self.find.read_text())
        self.assertEqual(original, (Path(result["backups"]) / "skills/find-skills/SKILL.md").read_bytes())
        self.assertIn("Keep this user preference.", (self.home / "AGENTS.md").read_text())

    def test_install_is_idempotent(self):
        installer.install(self.source, self.home, True, True)
        self.assertEqual([], installer.install(self.source, self.home, True, True)["changed"])
        self.assertEqual(1, self.find.read_text().count(installer.START))

    def test_conflicting_skill_is_not_overwritten(self):
        installer.install(self.source, self.home)
        path = self.home / "skills/skill-router/SKILL.md"
        path.write_text("User modification")
        with self.assertRaises(ValueError): installer.install(self.source, self.home, True, True)
        self.assertEqual("User modification", path.read_text())

    def test_missing_find_skills_fails_before_install(self):
        self.find.unlink()
        with self.assertRaises(ValueError): installer.install(self.source, self.home, True, True)
        self.assertFalse((self.home / "skills/skill-router").exists())

    def test_active_override_receives_hook(self):
        override = self.home / "AGENTS.override.md"
        override.write_text("Active override.")
        installer.install(self.source, self.home, True)
        self.assertIn(installer.START, override.read_text())
        self.assertNotIn(installer.START, (self.home / "AGENTS.md").read_text())

    def test_remove_hooks_preserves_other_text(self):
        installer.install(self.source, self.home, True, True)
        installer.install(self.source, self.home, remove_hooks=True)
        self.assertNotIn(installer.START, self.find.read_text())
        self.assertIn("Original instructions.", self.find.read_text())
        self.assertTrue((self.home / "skills/skill-router/SKILL.md").exists())

    def test_malformed_markers_fail_without_changes(self):
        self.find.write_text(installer.START + "bad block")
        with self.assertRaises(ValueError): installer.install(self.source, self.home, True, True)
        self.assertFalse((self.home / "skills/skill-router").exists())


if __name__ == "__main__": unittest.main()
