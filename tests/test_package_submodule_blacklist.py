import unittest
import tempfile
import shutil
import os
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(BASE_DIR, "src", "all-hooks")
HOOK_PATH = os.path.join(HOOKS_DIR, "package-submodule-blacklist")

BLACKLIST_FILE = ".git-workflow/hooks/package-submodule-blacklist.txt"
# _manifest that declares "rpms" as a package subdirectory.
SUBDIRECTORY_MANIFEST = "packages: []\nsubdirectories:\n  - rpms\n"
# Substring the hook prints when it rejects a submodule.
REJECTION_MESSAGE = "The following package submodule names are blacklisted"


class TestPackageSubmoduleBlacklist(unittest.TestCase):
    # Repository setup -----------------------------------------------------

    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="psb_test_")

        # Local development repository (pushes to the "factory" branch).
        self.repo_path = self.create_new_repo(os.path.join(self.tmpdir, "repo"), branch="factory")

        # Bare remote where the pre-receive hook runs. The hook is installed
        # per test via install_hook() so tests can push before it is active.
        self.bare_repo_path = self.create_new_repo(os.path.join(self.tmpdir, "bare_repo.git"), bare=True)
        self.run_git(["remote", "add", "origin", self.bare_repo_path])

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmpdir)

    def create_new_repo(self, path, bare=False, branch="main"):
        os.makedirs(path, exist_ok=True)
        args = ["init", "-q", "-b", branch]
        if bare:
            args.append("--bare")
        self.run_git(args, cwd=path)
        if not bare:
            self.run_git(["config", "user.email", "test@example.com"], cwd=path)
            self.run_git(["config", "user.name", "Test User"], cwd=path)
        return path

    def install_hook(self):
        hook = os.path.join(self.bare_repo_path, "hooks", "pre-receive")
        shutil.copy2(HOOK_PATH, hook)
        # A non-executable hook is skipped silently by git, which would let the
        # "allow" tests pass without ever exercising the hook. Fail loudly instead.
        self.assertTrue(os.access(hook, os.X_OK), "pre-receive hook is not executable")

    # Git helpers ----------------------------------------------------------

    def run_git(self, args, cwd=None, env=None):
        # Isolate git from any ambient user/system configuration so results are reproducible.
        env = {
            **os.environ,
            **(env or {}),
            "HOME": self.tmpdir,           # ignore ~/.gitconfig
            "GIT_CONFIG_NOSYSTEM": "1",    # ignore /etc/gitconfig
        }
        return subprocess.check_output(
            ["git"] + args, cwd=cwd or self.repo_path, encoding="utf-8", stderr=subprocess.STDOUT, env=env
        )

    def create_commit(self, files, msg="Commit"):
        for path, content in files.items():
            full_path = os.path.join(self.repo_path, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(content)
            self.run_git(["add", path])
        self.run_git(["commit", "-m", msg, "--allow-empty"])

    def add_submodule(self, name, path):
        sub_repo_path = os.path.join(self.tmpdir, name)
        if not os.path.exists(sub_repo_path):
            self.create_new_repo(sub_repo_path)
            with open(os.path.join(sub_repo_path, "file"), "w") as f:
                f.write("data")
            self.run_git(["add", "file"], cwd=sub_repo_path)
            self.run_git(["commit", "-m", "Initial"], cwd=sub_repo_path)

        self.run_git(["-c", "protocol.file.allow=always", "submodule", "add", sub_repo_path, path])
        self.run_git(["commit", "-m", f"Add submodule {name}"])

    def remove_submodule(self, path):
        self.run_git(["submodule", "deinit", "-f", path])
        self.run_git(["rm", "-f", path])
        self.run_git(["commit", "-m", f"Remove submodule {path}"])

    # Assertions -----------------------------------------------------------

    def push(self, env=None):
        return self.run_git(["push", "origin", "factory"], env=env)

    def local_head(self):
        return self.run_git(["rev-parse", "HEAD"]).strip()

    def remote_head(self):
        return self.run_git(["rev-parse", "refs/heads/factory"], cwd=self.bare_repo_path).strip()

    def assert_push_allowed(self):
        self.assertNotIn(REJECTION_MESSAGE, self.push())
        # Confirm the commit actually landed on the remote, not just that push didn't error.
        self.assertEqual(self.remote_head(), self.local_head())

    def assert_push_rejected(self, name):
        with self.assertRaises(subprocess.CalledProcessError) as cm:
            self.push()
        self.assertIn(REJECTION_MESSAGE, cm.exception.output)
        self.assertIn(name, cm.exception.output)

    # Tests ----------------------------------------------------------------

    def test_package_simple_allow(self):
        # Package files only, no blacklist -> push allowed.
        self.install_hook()
        self.create_commit({
            "pkg1.spec": "Name: pkg1\nVersion: 1\n",
            "pkg1.changes": "- Initial Version\n",
        })

        self.assert_push_allowed()

    def test_project_blacklist_new_reject(self):
        # Blacklisted submodule, no _manifest/_config files -> push rejected.
        self.install_hook()
        self.create_commit({BLACKLIST_FILE: "blacklisted-submodule\n"})
        self.add_submodule("blacklisted-submodule", "blacklisted-submodule")

        self.assert_push_rejected("blacklisted-submodule")

    def test_project_blacklist_pre_exists_reject(self):
        # Blacklist already on the remote; later adding a blacklisted submodule
        # under a manifest subdirectory -> push rejected.
        self.install_hook()
        self.create_commit({
            BLACKLIST_FILE: "blacklisted-submodule\n",
            "_manifest": SUBDIRECTORY_MANIFEST,
        })
        self.push()

        self.add_submodule("blacklisted-submodule", "rpms/blacklisted-submodule")

        self.assert_push_rejected("blacklisted-submodule")

    def test_project_config_allow(self):
        # Project with _config, submodule not in the blacklist -> push allowed.
        self.install_hook()
        self.create_commit({
            BLACKLIST_FILE: "blacklisted-submodule\n",
            "_config": "# OBS Project Config\n",
        })
        self.add_submodule("allowed-submodule", "allowed-submodule")

        self.assert_push_allowed()

    def test_project_config_reject(self):
        # Project with _config, blacklisted submodule -> push rejected.
        self.install_hook()
        self.create_commit({
            BLACKLIST_FILE: "blacklisted-submodule\n",
            "_config": "# OBS Project Config\n",
        })
        self.add_submodule("blacklisted-submodule", "blacklisted-submodule")

        self.assert_push_rejected("blacklisted-submodule")

    def test_project_manifest_allow(self):
        # Project with _manifest, submodule not in the blacklist -> push allowed.
        self.install_hook()
        self.create_commit({
            BLACKLIST_FILE: "blacklisted-submodule\n",
            "_manifest": SUBDIRECTORY_MANIFEST,
        })
        self.add_submodule("allowed-submodule", "rpms/allowed-submodule")

        self.assert_push_allowed()

    def test_project_manifest_reject(self):
        # Project with _manifest, blacklisted submodule -> push rejected.
        self.install_hook()
        self.create_commit({
            BLACKLIST_FILE: "blacklisted-submodule\n",
            "_manifest": SUBDIRECTORY_MANIFEST,
        })
        self.add_submodule("blacklisted-submodule", "rpms/blacklisted-submodule")

        self.assert_push_rejected("blacklisted-submodule")

    def test_project_manifest_submodule_delete_allow(self):
        # Removing an already-pushed blacklisted submodule -> push allowed,
        # because the new revision no longer contains it.
        self.create_commit({
            BLACKLIST_FILE: "blacklisted-submodule\n",
            "_manifest": SUBDIRECTORY_MANIFEST,
        })
        self.add_submodule("blacklisted-submodule", "rpms/blacklisted-submodule")
        self.push()

        self.install_hook()
        self.remove_submodule("rpms/blacklisted-submodule")

        self.assert_push_allowed()

    def test_skip_env_bypasses_blacklist(self):
        # Blacklisted submodule pushed with the bypass env var set -> push allowed.
        # Same setup as the reject tests, so this also proves the hook actually runs.
        self.install_hook()
        self.create_commit({BLACKLIST_FILE: "blacklisted-submodule\n"})
        self.add_submodule("blacklisted-submodule", "blacklisted-submodule")

        output = self.push(env={"PACKAGE_SUBMODULE_BLACKLIST_SKIP": "1"})
        self.assertNotIn(REJECTION_MESSAGE, output)
        self.assertEqual(self.remote_head(), self.local_head())


if __name__ == "__main__":
    unittest.main()
