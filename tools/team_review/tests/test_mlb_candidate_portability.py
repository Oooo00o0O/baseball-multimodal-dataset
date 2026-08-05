from __future__ import annotations

import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
TOOL_ROOT = HERE.parents[1]
MLB_ROOT = TOOL_ROOT / "mlb_candidate_curation"
REPOSITORY_ROOT = TOOL_ROOT.parents[1]


class MlbCandidatePortabilityTests(unittest.TestCase):
    def test_required_portable_entry_points_are_present(self) -> None:
        for relative in (
            "start_mlb_candidate_curation.bat",
            "start_mlb_candidate_curation.ps1",
            "merge_team_results.bat",
            "merge_team_results.ps1",
            "requirements.txt",
            "static/vendor/wavesurfer-7.12.11/wavesurfer.esm.js",
            "static/vendor/wavesurfer-7.12.11/regions.esm.js",
            "static/vendor/wavesurfer-7.12.11/LICENSE",
        ):
            self.assertTrue((MLB_ROOT / relative).is_file(), relative)

    def test_frontend_has_no_cross_workbench_static_dependency(self) -> None:
        app = (MLB_ROOT / "static" / "app.js").read_text(encoding="utf-8")
        server = (MLB_ROOT / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("/shared/", app)
        self.assertNotIn("contact_audit_workbench", server)

    def test_launcher_has_no_codex_runtime_dependency(self) -> None:
        launcher = (MLB_ROOT / "start_mlb_candidate_curation.ps1").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("codex-runtimes", launcher)
        self.assertIn("-m venv", launcher)

    def test_runtime_data_and_media_are_git_ignored(self) -> None:
        ignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/review/mlb_candidate_curation/", ignore)
        self.assertIn("mlb_candidate_curation/.runtime/", ignore)
        self.assertIn("mlb_candidate_curation/merged_results/", ignore)


if __name__ == "__main__":
    unittest.main()
