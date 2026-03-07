"""Persistent workspace memory for project conventions and stack preferences."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, UTC
from pathlib import Path


PROJECT_MEMORY_DIR = Path.home() / ".codex" / "memories" / "neudev"

TECHNOLOGY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("React", ("react",)),
    ("Next.js", ("next.js", "nextjs", " next ")),
    ("Vue", ("vue",)),
    ("Nuxt", ("nuxt",)),
    ("Svelte", ("svelte",)),
    ("Angular", ("angular", "@angular/core")),
    ("TypeScript", ("typescript", " ts ", ".ts", ".tsx")),
    ("JavaScript", ("javascript", " js ", ".js", ".jsx")),
    ("Flutter", ("flutter",)),
    ("Dart", ("dart",)),
    ("Python", ("python",)),
    ("FastAPI", ("fastapi",)),
    ("Django", ("django",)),
    ("Flask", ("flask",)),
    ("Node.js", ("node", "node.js")),
    ("Express", ("express",)),
    ("NestJS", ("nestjs", "@nestjs/core")),
    ("Tailwind CSS", ("tailwind", "tailwindcss")),
]

STYLE_DIRECTIVES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:2|two)[ -]?spaces?\b", re.I), "Indentation should use 2 spaces."),
    (re.compile(r"\b(?:4|four)[ -]?spaces?\b", re.I), "Indentation should use 4 spaces."),
    (re.compile(r"\btabs?\b", re.I), "Indentation should be tab-based."),
    (re.compile(r"\bsingle quotes?\b", re.I), "String literals should use single quotes."),
    (re.compile(r"\bdouble quotes?\b", re.I), "String literals should use double quotes."),
    (re.compile(r"\btype hints?\b", re.I), "Python functions should include return type hints."),
    (re.compile(r"\b(?:avoid|remove|drop)\s+type hints?\b", re.I), "Avoid adding Python return type hints unless required by the project."),
    (re.compile(r"\bexplicit exports?\b", re.I), "JS/TS modules should use explicit `export` declarations."),
    (re.compile(r"\bdefault exports?\b", re.I), "JS/TS modules should prefer `export default` where the project expects it."),
    (re.compile(r"\bclean architecture\b", re.I), "Preserve clean architecture layering."),
    (re.compile(r"\bmvc\b", re.I), "Preserve the existing MVC structure."),
    (re.compile(r"\bfeature[- ]first\b", re.I), "Organize code by feature-first structure."),
    (re.compile(r"\batomic design\b", re.I), "Preserve the existing atomic-design component structure."),
    (re.compile(r"\bmaterial design\b", re.I), "Follow a Material Design component style."),
]

CHANGE_HINTS = (
    "use",
    "prefer",
    "follow",
    "switch",
    "migrate",
    "convert",
    "rewrite",
    "build",
    "create",
    "adopt",
    "change",
    "move to",
    "update to",
)


class ProjectMemoryStore:
    """Persist learned workspace conventions and user-directed preferences."""

    def __init__(self, workspace_path: str | Path):
        self.workspace = Path(workspace_path).resolve()
        self.path = PROJECT_MEMORY_DIR / f"{self._workspace_key(self.workspace)}.json"
        self.data = self._load()

    def sync_from_analysis(self, analysis: dict) -> bool:
        """Persist observed workspace structure and conventions."""
        updated = dict(self.data)
        changed = False

        observed_components = [
            f"{component['path']} [{component['role']}/{component['project_type']}]"
            for component in analysis.get("components", [])
        ]
        observed_technologies = list(analysis.get("technologies", []))
        observed_conventions = list(analysis.get("observed_conventions", analysis.get("conventions", [])))

        changed |= self._set(updated, "workspace", str(self.workspace))
        changed |= self._set(updated, "project_type", analysis.get("project_type", "unknown"))
        changed |= self._set(updated, "observed_components", observed_components)
        changed |= self._set(updated, "observed_technologies", observed_technologies)
        changed |= self._set(updated, "observed_conventions", observed_conventions)

        if changed:
            updated["updated_at"] = self._timestamp()
            self._save(updated)
        else:
            self.data = updated
        return changed

    def apply_user_directives(self, user_message: str) -> bool:
        """Capture explicit user requests that should override older memory."""
        preferred_technologies, preferred_conventions = self._extract_directives(user_message)
        if not preferred_technologies and not preferred_conventions:
            return False

        updated = dict(self.data)
        changed = False

        if preferred_technologies:
            merged_technologies = self._merge_values(
                preferred_technologies,
                updated.get("preferred_technologies", []),
            )
            changed |= self._set(updated, "preferred_technologies", merged_technologies)

        if preferred_conventions:
            merged_conventions = self._merge_notes(
                preferred_conventions,
                updated.get("preferred_conventions", []),
            )
            changed |= self._set(updated, "preferred_conventions", merged_conventions)

        if changed:
            updated["updated_at"] = self._timestamp()
            self._save(updated)
        else:
            self.data = updated
        return changed

    def get_active_conventions(self, observed_conventions: list[str] | None = None) -> list[str]:
        """Return conventions the agent should actively follow."""
        observed = observed_conventions or self.data.get("observed_conventions", [])
        preferred = self.data.get("preferred_conventions", [])
        return self._merge_notes(preferred, observed)

    def get_active_technologies(self, observed_technologies: list[str] | None = None) -> list[str]:
        """Return technologies the agent should prioritize in planning."""
        observed = observed_technologies or self.data.get("observed_technologies", [])
        preferred = self.data.get("preferred_technologies", [])
        return self._merge_values(preferred, observed)

    def get_prompt_notes(self, analysis: dict | None = None) -> list[str]:
        """Build compact memory notes for the system prompt."""
        observed_conventions = []
        observed_technologies = []
        if analysis:
            observed_conventions = list(analysis.get("observed_conventions", analysis.get("conventions", [])))
            observed_technologies = list(analysis.get("technologies", []))

        notes = []
        technologies = self.get_active_technologies(observed_technologies)
        conventions = self.get_active_conventions(observed_conventions)
        components = self.data.get("observed_components", [])

        if technologies:
            notes.append(f"Preferred stack: {', '.join(technologies[:6])}.")
            notes.append("Do not introduce a new language or framework unless the user explicitly asks for a stack change.")
        if components:
            notes.append(f"Preserve component layout: {', '.join(components[:4])}.")
        recent_turn_notes = self.data.get("recent_turn_notes", [])
        notes.extend(f"Recent work: {item}" for item in recent_turn_notes[:2])
        notes.extend(conventions[:4])
        return notes[:8]

    def record_turn(
        self,
        *,
        user_message: str,
        action_targets: list[str],
        review_notes: str = "",
        response: str = "",
    ) -> bool:
        """Persist a compact memory of recent work for the next turn."""
        summary = self._build_turn_summary(
            user_message=user_message,
            action_targets=action_targets,
            review_notes=review_notes,
            response=response,
        )
        if not summary:
            return False

        updated = dict(self.data)
        existing = [str(item) for item in updated.get("recent_turn_notes", [])]
        recent = [summary]
        recent.extend(item for item in existing if item != summary)
        recent = recent[:4]
        changed = self._set(updated, "recent_turn_notes", recent)

        if changed:
            updated["updated_at"] = self._timestamp()
            self._save(updated)
        else:
            self.data = updated
        return changed

    def has_saved_memory(self) -> bool:
        """Return whether meaningful workspace memory already exists."""
        return bool(
            self.data.get("observed_conventions")
            or self.data.get("preferred_conventions")
            or self.data.get("observed_technologies")
            or self.data.get("preferred_technologies")
            or self.data.get("recent_turn_notes")
        )

    def _load(self) -> dict:
        if not self.path.exists():
            return self._default_data()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_data()

    def _save(self, data: dict) -> None:
        try:
            PROJECT_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass
        self.data = data

    @staticmethod
    def _default_data() -> dict:
        return {
            "workspace": "",
            "project_type": "unknown",
            "observed_components": [],
            "observed_technologies": [],
            "preferred_technologies": [],
            "observed_conventions": [],
            "preferred_conventions": [],
            "recent_turn_notes": [],
            "updated_at": "",
        }

    @staticmethod
    def _workspace_key(workspace: Path) -> str:
        digest = hashlib.sha1(str(workspace).encode("utf-8"), usedforsecurity=False)
        return digest.hexdigest()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _set(target: dict, key: str, value) -> bool:
        if target.get(key) == value:
            return False
        target[key] = value
        return True

    @classmethod
    def _extract_directives(cls, user_message: str) -> tuple[list[str], list[str]]:
        text = f" {user_message.lower()} "
        if not any(hint in text for hint in CHANGE_HINTS):
            return [], []

        technologies = []
        for name, patterns in TECHNOLOGY_PATTERNS:
            if any(pattern in text for pattern in patterns):
                technologies.append(name)

        conventions = []
        for pattern, note in STYLE_DIRECTIVES:
            if pattern.search(user_message):
                conventions.append(note)

        return technologies, conventions

    @classmethod
    def _merge_notes(cls, preferred: list[str], observed: list[str]) -> list[str]:
        categories = {cls._note_category(note) for note in preferred}
        categories.discard(None)

        merged = []
        for note in preferred:
            if note not in merged:
                merged.append(note)

        for note in observed:
            category = cls._note_category(note)
            if category in categories:
                continue
            if note not in merged:
                merged.append(note)
        return merged

    @staticmethod
    def _merge_values(primary: list[str], secondary: list[str]) -> list[str]:
        merged = []
        seen = set()
        for value in [*primary, *secondary]:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
        return merged

    @staticmethod
    def _note_category(note: str) -> str | None:
        lowered = note.lower()
        if "indentation" in lowered or "spaces" in lowered or "tab-based" in lowered:
            return "indentation"
        if "quote" in lowered:
            return "quotes"
        if "type hint" in lowered:
            return "typing"
        if "export" in lowered:
            return "exports"
        if "test" in lowered and "naming" in lowered:
            return "tests"
        if "component layout" in lowered or "directory structure" in lowered or "component boundaries" in lowered:
            return "structure"
        if "architecture" in lowered or "mvc" in lowered or "feature-first" in lowered or "atomic-design" in lowered:
            return "architecture"
        return None

    @staticmethod
    def _build_turn_summary(
        *,
        user_message: str,
        action_targets: list[str],
        review_notes: str,
        response: str,
    ) -> str:
        """Summarize the most recent turn in one compact memory line."""
        request = " ".join(str(user_message or "").split())
        if not request:
            return ""
        if len(request) > 72:
            request = request[:69].rstrip() + "..."

        targets = []
        seen = set()
        for target in action_targets:
            cleaned = str(target or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            targets.append(cleaned)
            if len(targets) >= 3:
                break

        issue = " ".join(str(review_notes or "").replace("-", " ").split())
        if issue:
            if len(issue) > 70:
                issue = issue[:67].rstrip() + "..."
            return f"{request} | follow-up issue: {issue}"

        if targets:
            return f"{request} | touched: {', '.join(targets)}"

        outcome = " ".join(str(response or "").split())
        if outcome:
            if len(outcome) > 70:
                outcome = outcome[:67].rstrip() + "..."
            return f"{request} | outcome: {outcome}"
        return request
