import unittest
import tempfile
import shutil
import os
import subprocess
import sys

# setup paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(BASE_DIR, "src", "all-hooks")
HOOK_PATH = os.path.join(HOOKS_DIR, "package-submodule-blacklist")


class TestPackageSubmoduleBlacklist(unittest.TestCase):
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

    def install_pre_receive_hook(self, repo_path):
        pre_receive = os.path.join(repo_path, "hooks", "pre-receive")
        shutil.copy2(HOOK_PATH, pre_receive)

    def install_pre_push_hook(self, repo_path):
        pre_push = os.path.join(repo_path, ".git", "hooks", "pre-push")
        os.makedirs(os.path.dirname(pre_push), exist_ok=True)
        shutil.copy2(HOOK_PATH, pre_push)

    def setUp(self):
        self.old_cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="psb_test_")

        # local repo for development
        self.repo_path = self.create_new_repo(os.path.join(self.tmpdir, "repo"), branch="factory")

        # bare repo for hook execution
        self.bare_repo_path = self.create_new_repo(os.path.join(self.tmpdir, "bare_repo.git"), bare=True)

        # setup remote
        self.run_git(["remote", "add", "origin", self.bare_repo_path], cwd=self.repo_path)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmpdir)

    def run_git(self, args, cwd=None, env=None):
        env = {
            **os.environ,
            **(env or {}),
            "HOME": self.tmpdir,
            # allow file protocol for submodules
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        return subprocess.check_output(
            ["git"] + args, cwd=cwd or self.repo_path, encoding="utf-8", stderr=subprocess.STDOUT, env=env
        )

    def create_commit(self, files=None, msg="Commit", cwd=None):
        if files:
            for path, content in files.items():
                full_path = os.path.join(cwd or self.repo_path, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(content)
                self.run_git(["add", path], cwd=cwd)
        self.run_git(["commit", "-m", msg, "--allow-empty"], cwd=cwd)
        return self.run_git(["rev-parse", "HEAD"], cwd=cwd).strip()

    def add_submodule(self, name, path, cwd=None):
        sub_repo_path = os.path.join(self.tmpdir, name)
        if not os.path.exists(sub_repo_path):
            os.makedirs(sub_repo_path)
            self.run_git(["init", "-q"], cwd=sub_repo_path)
            self.run_git(["config", "user.email", "test@example.com"], cwd=sub_repo_path)
            self.run_git(["config", "user.name", "Test User"], cwd=sub_repo_path)
            with open(os.path.join(sub_repo_path, "file"), "w") as f:
                f.write("data")
            self.run_git(["add", "file"], cwd=sub_repo_path)
            self.run_git(["commit", "-m", "Initial", "--allow-empty"], cwd=sub_repo_path)

        self.run_git(["submodule", "add", sub_repo_path, path], cwd=cwd)
        self.run_git(["commit", "-m", f"Add submodule {name}"], cwd=cwd)
        return self.run_git(["rev-parse", "HEAD"], cwd=cwd).strip()

    def test_integration_no_blacklist(self):
        self.install_pre_receive_hook(self.bare_repo_path)
        files = {
            "pkg1/file": "content",
            "_manifest": "packages:\n  - pkg1\n",
        }
        self.create_commit(files)
        self.run_git(["push", "origin", "factory"])

    def test_integration_with_blacklist_match(self):
        self.install_pre_receive_hook(self.bare_repo_path)
        files = {
            ".git-workflow/hooks/package-submodule-blacklist.txt": "pkg1\n",
            "_manifest": "packages:\n  - pkg1\n",
        }
        self.create_commit(files)
        self.add_submodule("pkg1", "pkg1")

        with self.assertRaises(subprocess.CalledProcessError) as cm:
            self.run_git(["push", "origin", "factory"])

        self.assertIn("blacklisted", cm.exception.output)
        self.assertIn("pkg1", cm.exception.output)

    def test_integration_pre_push_blacklist_match(self):
        # install hook as pre-push in local repo
        self.install_pre_push_hook(self.repo_path)

        files = {
            ".git-workflow/hooks/package-submodule-blacklist.txt": "pkg1\n",
            "_manifest": "packages:\n  - pkg1\n",
        }
        self.create_commit(files)
        self.add_submodule("pkg1", "pkg1")

        with self.assertRaises(subprocess.CalledProcessError) as cm:
            # this should trigger pre-push
            self.run_git(["push", "origin", "factory"])

        self.assertIn("blacklisted", cm.exception.output)
        self.assertIn("pkg1", cm.exception.output)

    def test_no_manifest_file_with_blacklist_match(self):
        """
        Test that when _manifest does not exist in the git history at all,
        but the git repo is detected as a project due to presence of _config file,
        the hook still runs, considers all top-level subdirectories/submodules
        as packages, and correctly catches blacklisted submodules.
        """
        self.install_pre_receive_hook(self.bare_repo_path)
        files = {
            ".git-workflow/hooks/package-submodule-blacklist.txt": "pkg1\n",
            "_config": "",
        }
        self.create_commit(files)
        self.add_submodule("pkg1", "pkg1")

        with self.assertRaises(subprocess.CalledProcessError) as cm:
            self.run_git(["push", "origin", "factory"])

        # we assert that the hook output contains the expected blacklist error,
        # not a python AttributeError traceback caused by store.manifest set to None
        self.assertIn("The following package submodule names are blacklisted", cm.exception.output)
        self.assertIn("pkg1", cm.exception.output)


if __name__ == "__main__":
    unittest.main()
