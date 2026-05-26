import unittest
import os
import subprocess
import shutil
import tempfile
import time


# setup paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(BASE_DIR, "src", "all-hooks")
HOOK_PATH = os.path.join(HOOKS_DIR, "git-lfs-check")


class GitLfsCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.remote_dir = os.path.join(self.tmp_dir, "remote.git")
        self.local_dir = os.path.join(self.tmp_dir, "local")

        self.env = {
            **os.environ,
            "HOME": self.tmp_dir,
            "GIT_CONFIG_NOSYSTEM": "1",
        }

        subprocess.run(["git", "init", "-b", "main", "--bare", self.remote_dir], env=self.env, stdout=subprocess.DEVNULL, check=True)

        # install hook
        pre_receive = os.path.join(self.remote_dir, "hooks", "pre-receive")
        shutil.copy2(HOOK_PATH, pre_receive)

        subprocess.run(["git", "init", "-b", "main", self.local_dir], env=self.env, stdout=subprocess.DEVNULL, check=True)
        subprocess.run(
            ["git", "-C", self.local_dir, "config", "user.email", "test@example.com"], env=self.env, check=True
        )
        subprocess.run(["git", "-C", self.local_dir, "config", "user.name", "Test User"], env=self.env, check=True)
        subprocess.run(
            ["git", "-C", self.local_dir, "remote", "add", "origin", self.remote_dir], env=self.env, check=True
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def push(self, force=False):
        cmd = ["git", "-C", self.local_dir, "push", "origin", "main"]
        if force:
            cmd.insert(4, "-f")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=self.env, check=False)
        return res

    def run_git_local(self, *args, **kwargs):
        """Helper to run git commands in the local repo silently."""
        kwargs.setdefault("env", self.env)
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
        kwargs.setdefault("universal_newlines", True)
        check = kwargs.pop("check", True)
        return subprocess.run(["git", "-C", self.local_dir] + list(args), check=check, **kwargs)

    def write_local_file(self, filename, content, mode="w"):
        """Helper to write a file in the local repository with UTF-8 encoding."""
        with open(os.path.join(self.local_dir, filename), mode, encoding="utf-8") as f:
            f.write(content)

    def test_scenarios(self):
        # 1. Push without .gitattributes -> PASS
        self.write_local_file("README", "hi")
        self.run_git_local("add", "README", check=True)
        self.run_git_local("commit", "-m", "init", check=True)
        res = self.push()
        self.assertEqual(res.returncode, 0, res.stderr)

        # 2. Correct LFS pointer -> PASS
        self.write_local_file(".gitattributes", "*.png filter=lfs")
        self.write_local_file("img.png", "version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 10\n")
        self.run_git_local("add", ".", check=True)
        self.run_git_local("commit", "-m", "lfs", check=True)
        res = self.push()
        self.assertEqual(res.returncode, 0, res.stderr)

        # 3. Bad LFS file (should be pointer but isn't) -> FAIL
        blob_hash = subprocess.run(
            ["git", "-C", self.local_dir, "hash-object", "-w", "--stdin"],
            input="this is not a pointer",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True,
            env=self.env,
        ).stdout.strip()

        self.run_git_local("update-index", "--add", "--cacheinfo", "100644", blob_hash, "bad.png", check=True)
        self.run_git_local("commit", "-m", "bad lfs", check=True)

        res = self.push()
        self.assertNotEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertIn("matches LFS attribute but is NOT an LFS pointer", output)

    def test_multi_commit_history(self):
        """Test history where LFS rules are added after files already exist."""
        # 1. First commit: Add a PNG directly (no LFS rules yet)
        self.write_local_file("legacy.png", "I am a direct png, not a pointer")
        self.run_git_local("add", "legacy.png", check=True)
        self.run_git_local("commit", "-m", "add legacy png", check=True)

        # 2. Second commit: Add .gitattributes and a valid LFS pointer
        self.write_local_file(".gitattributes", "*.png filter=lfs\n")
        self.write_local_file("valid_lfs.png", "version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 10\n")
        self.run_git_local("add", ".", check=True)
        self.run_git_local("commit", "-m", "enable lfs and add valid png", check=True)

        # 3. Third commit: Add more files
        self.write_local_file("new_lfs.png", "version https://git-lfs.github.com/spec/v1\noid sha256:456\nsize 20\n")
        self.write_local_file("regular.txt", "just a text file")
        self.run_git_local("add", ".", check=True)
        self.run_git_local("commit", "-m", "more files", check=True)

        # 4. Push all 3 commits at once
        res = self.push()

        self.assertNotEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertIn("legacy.png: matches LFS attribute but is NOT an LFS pointer", output)

    def test_special_filenames(self):
        """Test filenames that are tricky to parse (quotes, colons)."""
        # 1. File named precisely '"' (double quote)
        quote_file = '"'
        self.write_local_file(quote_file, "content")

        # 2. File with colons, matched by LFS
        colon_file = "with:multiple:colons.png"
        self.write_local_file(colon_file, "version https://git-lfs.github.com/spec/v1\noid sha256:789\nsize 10\n")

        self.write_local_file(".gitattributes", f'"{colon_file}" filter=lfs\n', mode="a")

        self.run_git_local("add", ".", check=True)
        self.run_git_local("commit", "-m", "special names", check=True)

        res = self.push()
        self.assertEqual(res.returncode, 0, f"Push failed with special names: {res.stderr}")

    def test_performance_20k_files(self):
        self.write_local_file(".gitattributes", "*.png filter=lfs\n")

        num_files = 20000
        for i in range(num_files):
            fname = f"file_{i}.txt"
            self.write_local_file(fname, f"content for file {i}")

        self.run_git_local("add", ".", check=True)
        self.run_git_local("commit", "-m", "add 20k files", check=True)

        start = time.time()
        res = self.push()
        duration = time.time() - start

        self.assertEqual(res.returncode, 0, res.stderr)
        # the limit is quite high, just to catch serious regressions; it should normally finish in about 1 second on a decent hardware
        expected_duration = 5
        self.assertLess(duration, expected_duration, "LFS check for {num_files} files took: {duration:.4f}s")


if __name__ == "__main__":
    unittest.main()
