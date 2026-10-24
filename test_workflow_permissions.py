from pathlib import Path
import re
import unittest


class WorkflowPermissionTests(unittest.TestCase):
    def test_ci_declares_least_privilege_github_token_permissions(self) -> None:
        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^permissions:\s*\n((?:^[ \t]+[^\n]*\n)+)",
            workflow,
        )
        self.assertIsNotNone(
            match,
            "CI must declare explicit least-privilege GITHUB_TOKEN permissions",
        )
        permissions = match.group(1)
        self.assertRegex(permissions, r"(?m)^[ \t]+contents:\s*read\s*$")
        self.assertNotRegex(
            permissions,
            r"(?m)^[ \t]+(?:contents|pull-requests|issues|actions|checks):\s*write\s*$",
        )


if __name__ == "__main__":
    unittest.main()
