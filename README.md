# Git OBS Hooks

A tool for managing and running git hooks in the Open Build Service (OBS) ecosystem,
for both client-side (git, osc) and server-side (Gitea) operations.

## Installation

**Note:** Installing these hooks will override any existing git hooks by redirecting the `core.hooksPath` git configuration.

### Client-side (for the current repository)

```bash
/usr/libexec/git-obs-hooks/git-obs-hooks-install
```
This will configure the current repository to use the OBS hooks.

### Server-side (for all Gitea repositories)

Run these commands as the `gitea` user:
```bash
su - gitea
/usr/libexec/git-obs-hooks/gitea-hooks-install
```

## Extending Hooks

You can add your own custom hooks.

### System-wide hooks
Place your executable hook scripts in:
- `/usr/libexec/git-obs-hooks/git-obs/*.d/` for client-side hooks.
- `/usr/libexec/git-obs-hooks/gitea/*.d/` for server-side hooks.

It's recommended to package these hooks as RPMs.
Use 'git-obs-hooks-' as the RPM package name prefix.

### User-specific hooks (client-side only)
Place your executable hook scripts in:
- `~/.local/share/git-obs-hooks/*.d/`

## Debugging

Enable verbose output by setting these environment variables:

```bash
export GIT_OBS_HOOKS_VERBOSE=1
export GIT_OBS_HOOKS_DEBUG=1
```

## How it Works

The `git-obs-hooks` system works by telling Git to use a different directory for its hooks.

### Centralized Hook Execution

The installation scripts (`git-obs-hooks-install` for client-side and `gitea-hooks-install` for server-side) configure Git's `core.hooksPath` to point to the `git-obs-hooks` directory (e.g., `/usr/libexec/git-obs-hooks/git-obs`).

When a Git event occurs (like a commit or push), Git runs the corresponding hook script from this central directory.

### Drop-in Directories

Each hook script (e.g., `pre-commit`, `pre-receive`) is a simple wrapper that executes all the executable scripts within its corresponding drop-in directory (e.g., `pre-commit.d/`, `pre-receive.d/`).

These drop-in directories can be in two locations:
*   **System-wide:** `/usr/libexec/git-obs-hooks/` (for both `git-obs` and `gitea` hooks)
*   **User-specific (client-side only):** `~/.local/share/git-obs-hooks/`

Scripts in the user-specific directory are executed before the scripts in the system-wide directory.

### Execution Order and Failure

Scripts within a drop-in directory are executed in sequence based on their filename.

The execution chain stops immediately if any script exits with a non-zero status code. This "fail-fast" approach ensures that failing hooks prevent the Git operation from continuing.

### Compatibility

This system takes precedence over other hook management tools like `git-lfs`. The `git-obs-hooks` package provides its own versions of hooks for `git-lfs` to ensure compatibility.

For more information on specific git hooks, see the `githooks(5)` man page.
