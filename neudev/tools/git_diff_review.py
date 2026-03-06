"""Git diff review tool for NeuDev."""

from __future__ import annotations

import subprocess

from neudev.tools.base import BaseTool, ToolError


class GitDiffReviewTool(BaseTool):
    """Summarize local git changes for review."""

    @property
    def name(self) -> str:
        return "git_diff_review"

    @property
    def description(self) -> str:
        return (
            "Review local git changes with status, changed files, and trimmed patch output. "
            "Useful for reviewer-style checks focused on what changed."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Git repository directory. Defaults to workspace root.",
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional subset of paths to review.",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Context lines for patch output. Default 1.",
                },
            },
        }

    def execute(self, directory: str = ".", paths: list[str] = None, context_lines: int = 1, **kwargs) -> str:
        repo_dir = self.resolve_directory(directory, must_exist=True)
        if not repo_dir.is_dir():
            raise ToolError(f"Not a directory: {repo_dir}")

        if not self._is_git_repo(repo_dir):
            raise ToolError(f"Not a git repository: {repo_dir}")

        scoped_paths = []
        for path in paths or []:
            resolved = self._resolve_repo_path(repo_dir, path)
            scoped_paths.append(str(resolved.relative_to(repo_dir)).replace("\\", "/"))

        status = self._run_git(repo_dir, ["status", "--short", "--untracked-files=all", "--", *scoped_paths])
        if status.returncode != 0:
            raise ToolError(self._trim(status.stderr or status.stdout))

        status_text = (status.stdout or "").strip()
        if not status_text:
            return f"Git diff review: {repo_dir}\nNo local changes."

        stat = self._run_git(repo_dir, ["diff", "--stat", "HEAD", "--", *scoped_paths])
        patch = self._run_git(
            repo_dir,
            ["diff", f"--unified={max(0, context_lines)}", "--no-ext-diff", "HEAD", "--", *scoped_paths],
        )

        lines = [
            f"Git diff review: {repo_dir}",
            "",
            "Status:",
            status_text,
            "",
        ]
        if stat.stdout.strip():
            lines.extend(["Diff Stat:", stat.stdout.strip(), ""])
        lines.extend(["Patch:", self._trim(patch.stdout or "(no patch output)")])
        return "\n".join(lines)

    @staticmethod
    def _run_git(repo_dir, args):
        command = ["git", *args]
        return subprocess.run(
            command,
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def _is_git_repo(self, repo_dir) -> bool:
        result = self._run_git(repo_dir, ["rev-parse", "--is-inside-work-tree"])
        return result.returncode == 0 and (result.stdout or "").strip() == "true"

    def _resolve_repo_path(self, repo_dir, path: str):
        raw = self.resolve_path(path, must_exist=False)
        if raw.is_relative_to(repo_dir):
            return raw

        repo_relative = self.resolve_path(f"{repo_dir.name}/{path}", must_exist=False)
        if repo_relative.is_relative_to(repo_dir):
            return repo_relative

        direct = (repo_dir / path).expanduser().resolve()
        if direct.is_relative_to(repo_dir) and self._is_in_workspace(direct):
            return direct

        raise ToolError(f"Path must stay inside the git repository: {path}")

    @staticmethod
    def _trim(text: str, limit: int = 5000) -> str:
        content = text.strip()
        if len(content) > limit:
            return content[:limit] + "\n... (output truncated)"
        return content or "(no output)"
