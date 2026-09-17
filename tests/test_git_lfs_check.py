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

    def push(self, force=False, ref="main"):
        """Helper to run git push to the remote repository."""
        cmd = ["git", "-C", self.local_dir, "push", "origin", ref]
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

    def import_history(self, commits):
        """Build a linear commit history via `git fast-import` for fast setup of large histories.

        `commits` is a list of (message, {path: content_bytes}) tuples; each entry
        produces one commit on top of the previous one.
        """
        def data(content: bytes) -> bytes:
            return f"data {len(content)}\n".encode() + content + b"\n"

        stream = bytearray()
        for mark, (message, files) in enumerate(commits, start=1):
            stream += b"commit refs/heads/main\n"
            stream += f"mark :{mark}\n".encode()
            stream += f"committer Test User <test@example.com> {1600000000 + mark} +0000\n".encode()
            stream += data(message.encode())
            if mark > 1:
                stream += f"from :{mark - 1}\n".encode()
            for path, content in files.items():
                stream += f"M 100644 inline {path}\n".encode()
                stream += data(content)

        subprocess.run(
            ["git", "-C", self.local_dir, "fast-import", "--quiet"],
            input=bytes(stream),
            env=self.env,
            check=True,
        )

    def test_lfs_lifecycle_scenarios(self):
        """Verify LFS check behavior across step-by-step pushes to a branch.

        1. Push regular files without .gitattributes (PASS).
        2. Add .gitattributes with 'filter=lfs' and a valid LFS pointer (PASS).
        3. Modify LFS file where .gitattributes is unchanged (PASS).
        4. Push non-compliant files (raw LFS files and untracked pointers) (FAIL).
        """
        # 1. Push without .gitattributes -> PASS
        self.write_local_file("README", "hi")
        self.run_git_local("add", "README")
        self.run_git_local("commit", "-m", "init")
        res = self.push()
        self.assertEqual(res.returncode, 0, res.stderr)

        # 2. Correct LFS pointer -> PASS
        self.write_local_file(".gitattributes", "*.png filter=lfs\n")
        self.write_local_file("img.png", "version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 10\n")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "enable lfs")
        res = self.push()
        self.assertEqual(res.returncode, 0, res.stderr)

        # 3. Modify LFS pointer without changing .gitattributes -> PASS
        self.write_local_file("img.png", "version https://git-lfs.github.com/spec/v1\noid sha256:456\nsize 20\n")
        self.run_git_local("add", "img.png")
        self.run_git_local("commit", "-m", "update lfs pointer")
        res = self.push()
        self.assertEqual(res.returncode, 0, res.stderr)

        # 4. Subsequent push with non-compliant files (both missing pointer and unwanted pointer) -> FAIL
        self.write_local_file("bad.png", "this is not a pointer")
        self.write_local_file("img.png", "raw image data")
        self.write_local_file("untracked_pointer.txt", "version https://git-lfs.github.com/spec/v1\noid sha256:789\nsize 10\n")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "non-compliant files")

        res = self.push()
        self.assertNotEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertIn("bad.png: matches LFS attribute but is NOT an LFS pointer", output)
        self.assertIn("img.png: matches LFS attribute but is NOT an LFS pointer", output)
        self.assertIn("untracked_pointer.txt: is NOT matched by LFS attribute but IS an LFS pointer", output)

    def test_legacy_untracked_files_in_multi_commit_history(self):
        """Verify LFS check across multi-commit history pushed in a single batch.

        1. Early commit adds a file directly (no LFS rules yet).
        2. Later commit adds .gitattributes enabling LFS for that file pattern.
        3. Subsequent commits add more files.
        When pushing all commits at once, the hook inspects history and rejects the push
        because an earlier commit contained a raw file matching the LFS rule.
        """
        # 1. First commit: Add a PNG directly (no LFS rules yet)
        self.write_local_file("legacy.png", "I am a direct png, not a pointer")
        self.run_git_local("add", "legacy.png")
        self.run_git_local("commit", "-m", "add legacy png")

        # 2. Second commit: Add .gitattributes and a valid LFS pointer
        self.write_local_file(".gitattributes", "*.png filter=lfs\n")
        self.write_local_file("valid_lfs.png", "version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 10\n")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "enable lfs and add valid png")

        # 3. Third commit: Add more files
        self.write_local_file("new_lfs.png", "version https://git-lfs.github.com/spec/v1\noid sha256:456\nsize 20\n")
        self.write_local_file("regular.txt", "just a text file")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "more files")

        # 4. Push all 3 commits at once
        res = self.push()

        self.assertNotEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertIn("legacy.png: matches LFS attribute but is NOT an LFS pointer", output)

    def test_special_characters_in_filenames(self):
        """Verify handling of filenames with special characters (quotes, colons, spaces).

        1. Parse Git's quoted paths in `check-attr` and `ls-tree` for valid LFS pointers (PASS).
        2. Unquote paths in error messages when rejecting non-compliant files (FAIL).
        """
        # 1. File named precisely '"' (double quote)
        quote_file = '"'
        self.write_local_file(quote_file, "content")

        # 2. File with colons, spaces, matched by LFS
        colon_file = "with: multiple:colons and :spaces.png"
        self.write_local_file(colon_file, "version https://git-lfs.github.com/spec/v1\noid sha256:789\nsize 10\n")

        self.write_local_file(".gitattributes", f'"{colon_file}" filter=lfs\n', mode="a")

        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "special names")

        res = self.push()
        self.assertEqual(res.returncode, 0, f"Push failed with special names: {res.stderr}")

        # 3. Non-compliant file with special name -> FAIL and check unquoted path in error
        bad_colon_file = "bad: colon and space.png"
        self.write_local_file(bad_colon_file, "not a pointer")
        self.write_local_file(".gitattributes", f'"{bad_colon_file}" filter=lfs\n', mode="a")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "bad special name")

        res_bad = self.push()
        self.assertNotEqual(res_bad.returncode, 0)
        output = res_bad.stdout + res_bad.stderr
        self.assertIn(f"{bad_colon_file}: matches LFS attribute but is NOT an LFS pointer", output)

    def test_non_ascii_filenames(self):
        """Verify handling of non-ASCII UTF-8 filenames for LFS pointers and raw files."""
        self.write_local_file(".gitattributes", "*.png filter=lfs\n")

        valid_non_ascii_file = "tëst_äöü_日本語.png"
        self.write_local_file(
            valid_non_ascii_file,
            "version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 10\n",
        )
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "valid non-ascii lfs")

        res_valid = self.push()
        self.assertEqual(res_valid.returncode, 0, f"Push failed for valid non-ASCII file: {res_valid.stderr}")

        bad_non_ascii_file = "bad_äöü_日本語.png"
        self.write_local_file(bad_non_ascii_file, "raw binary image content")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "bad non-ascii file")

        res_bad = self.push()
        self.assertNotEqual(res_bad.returncode, 0)
        output = res_bad.stdout + res_bad.stderr
        self.assertIn(f"{bad_non_ascii_file}: matches LFS attribute but is NOT an LFS pointer", output)

    def test_merge_commit_with_untracked_pointer_is_rejected(self):
        """Reject untracked LFS pointers introduced during merge commit conflict resolution."""
        self.write_local_file("file.txt", "base content\n")
        self.run_git_local("add", "file.txt")
        self.run_git_local("commit", "-m", "base commit")
        self.push()

        self.run_git_local("checkout", "-b", "feature")
        self.write_local_file("file.txt", "feature content\n")
        self.run_git_local("commit", "-am", "feature commit")

        self.run_git_local("checkout", "main")
        self.write_local_file("file.txt", "main content\n")
        self.run_git_local("commit", "-am", "main commit")

        self.run_git_local("merge", "feature", check=False)
        self.write_local_file("file.txt", "resolved content\n")
        self.write_local_file(
            "untracked_pointer.txt",
            "version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 10\n",
        )
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "merge with untracked pointer")

        res = self.push()
        self.assertNotEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertIn("untracked_pointer.txt: is NOT matched by LFS attribute but IS an LFS pointer", output)

    def test_documentation_mentioning_lfs_is_not_treated_as_pointer(self):
        """Allow files that reference the Git LFS specification without being pointers."""
        self.write_local_file(
            "doc.md",
            "version https://git-lfs.github.com/spec/v1 is the specification URL for Git LFS.\n"
            "Here is how to configure it in your repository.\n",
        )
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "add documentation")

        res = self.push()
        self.assertEqual(res.returncode, 0, f"Push failed for documentation file: {res.stderr}")

    def test_large_repository_scaling_20k_files(self):
        """Verify performance when processing 20,000 files.

        Ensures batched `cat-file` validation completes within expected time limits.
        """
        self.write_local_file(".gitattributes", "*.png filter=lfs\n")

        num_files = 20000
        for i in range(num_files):
            fname = f"file_{i}.txt"
            self.write_local_file(fname, f"content for file {i}")

        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "add 20k files")

        start = time.time()
        res = self.push()
        duration = time.time() - start

        self.assertEqual(res.returncode, 0, res.stderr)
        # Allow some room for slower test environments while catching large regressions.
        expected_duration = 3
        self.assertLess(duration, expected_duration, f"LFS check for {num_files} files took: {duration:.4f}s")

    def test_large_history_without_lfs_performs_quickly(self):
        """Verify a large, LFS-free commit history pushes quickly (like importing an existing large repository)."""
        num_commits = 3000
        commits = [(f"commit {i}", {"file.txt": f"content {i}\n".encode()}) for i in range(num_commits)]
        self.import_history(commits)

        start = time.time()
        res = self.push()
        duration = time.time() - start

        self.assertEqual(res.returncode, 0, res.stderr)
        # Allow some room for slower test environments while catching per-revision scanning.
        expected_duration = 3
        self.assertLess(duration, expected_duration, f"push of {num_commits} LFS-free commits took {duration:.4f}s")

    def test_large_history_with_lfs_file_is_detected(self):
        """Verify a non-compliant LFS file is detected and rejected deep in history."""
        before, after = 500, 200

        commits = [(f"before {i}", {"README.md": f"line {i}\n".encode()}) for i in range(before)]
        commits.append((
            "introduce lfs rule with non-compliant file",
            {
                ".gitattributes": b"*.bin filter=lfs\n",
                "asset.bin": b"raw content that is not an lfs pointer\n" * 10,
            },
        ))
        commits += [(f"after {i}", {"README.md": f"after {i}\n".encode()}) for i in range(after)]
        self.import_history(commits)

        start = time.time()
        res = self.push()
        duration = time.time() - start

        self.assertNotEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertIn("asset.bin: matches LFS attribute but is NOT an LFS pointer", output)

        # The rule persists after it is introduced, so later revisions require a full check.
        expected_duration = 12
        total_commits = before + after + 1
        self.assertLess(duration, expected_duration, f"push with {total_commits} commits took {duration:.4f}s")

    def test_comment_and_negation_in_attributes_are_not_treated_as_lfs(self):
        """Comments and negations should not trigger LFS compliance checks."""
        self.write_local_file("README", "initial")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "initial commit")
        self.push()

        self.run_git_local("checkout", "-b", "feature_attr_semantics")
        self.write_local_file(".gitattributes", "# *.png filter=lfs\n*.png -filter=lfs\n")
        self.write_local_file("img.png", "raw png data")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "commented and negated lfs rules")

        res = self.push(ref="feature_attr_semantics")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_lfs_pointer_without_attributes_is_rejected(self):
        """Reject an LFS pointer when the revision has no attributes file."""
        self.write_local_file("README", "initial")
        self.run_git_local("add", "README")
        self.run_git_local("commit", "-m", "initial commit")
        self.push()

        self.write_local_file(
            "document.txt",
            "version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 10\n",
        )
        self.run_git_local("add", "document.txt")
        self.run_git_local("commit", "-m", "add untracked LFS pointer")

        res = self.push()

        self.assertNotEqual(res.returncode, 0)
        output = res.stdout + res.stderr
        self.assertIn("document.txt: is NOT matched by LFS attribute but IS an LFS pointer", output)

    def test_debug_and_verbose_logging_output(self):
        """Verify GIT_OBS_HOOKS_DEBUG and GIT_OBS_HOOKS_VERBOSE diagnostic output.

        1. Without environment flags, the hook operates silently.
        2. With GIT_OBS_HOOKS_DEBUG=1 and GIT_OBS_HOOKS_VERBOSE=1, the hook logs DEBUG messages
           for checked commits and VERBOSE messages for skipped commits.
        """
        # Initial commit on main without LFS attributes
        self.write_local_file("README", "initial")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "initial commit")
        self.push()

        # On feature_debug: commit 1 (no attributes) and commit 2 (with attributes)
        self.run_git_local("checkout", "-b", "feature_debug")
        self.write_local_file("doc.txt", "doc content")
        self.run_git_local("add", "doc.txt")
        self.run_git_local("commit", "-m", "commit 1: no attributes")

        self.write_local_file(".gitattributes", "*.png filter=lfs\n")
        self.write_local_file("img.png", "version https://git-lfs.github.com/spec/v1\noid sha256:456\nsize 10\n")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "commit 2: lfs enabled")

        # By default (no env vars), no debug or verbose output is printed
        res_normal = self.push(ref="feature_debug")
        self.assertEqual(res_normal.returncode, 0, res_normal.stderr)
        output_normal = res_normal.stdout + res_normal.stderr
        self.assertNotIn("DEBUG:", output_normal)
        self.assertNotIn("VERBOSE:", output_normal)

        # On feature_debug2: test GIT_OBS_HOOKS_DEBUG=1 and GIT_OBS_HOOKS_VERBOSE=1
        self.run_git_local("checkout", "-b", "feature_debug2", "main")
        self.write_local_file("doc2.txt", "doc content 2")
        self.run_git_local("add", "doc2.txt")
        self.run_git_local("commit", "-m", "commit 3: no attributes")
        c3_sha = self.run_git_local("rev-parse", "HEAD").stdout.strip()

        self.write_local_file(".gitattributes", "*.png filter=lfs\n")
        self.write_local_file("img2.png", "version https://git-lfs.github.com/spec/v1\noid sha256:789\nsize 10\n")
        self.run_git_local("add", ".")
        self.run_git_local("commit", "-m", "commit 4: lfs enabled")
        c4_sha = self.run_git_local("rev-parse", "HEAD").stdout.strip()

        self.env["GIT_OBS_HOOKS_DEBUG"] = "1"
        self.env["GIT_OBS_HOOKS_VERBOSE"] = "1"
        res_debug = self.push(ref="feature_debug2")
        self.assertEqual(res_debug.returncode, 0, res_debug.stderr)
        output_debug = res_debug.stdout + res_debug.stderr

        self.assertIn(f"DEBUG: checking LFS compliance for revision {c4_sha}", output_debug)
        self.assertIn(f"VERBOSE: skipping LFS compliance check for revision {c3_sha} (no LFS rule or pointer)", output_debug)
        self.assertNotIn(f"DEBUG: checking LFS compliance for revision {c3_sha}", output_debug)

if __name__ == "__main__":
    unittest.main()
