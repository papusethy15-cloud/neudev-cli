"""Context summarization and smart window management for NeuDev."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MessageScore:
    """Score for a conversation message."""

    message_index: int
    recency_score: float  # 0.0 to 1.0
    importance_score: float  # 0.0 to 1.0
    tool_result_score: float  # 0.0 to 1.0
    total_score: float

    def __lt__(self, other: "MessageScore") -> bool:
        return self.total_score < other.total_score


class ContextSummarizer:
    """Summarizes conversation context to preserve important information."""

    def __init__(self, max_context_messages: int = 40, summary_threshold: int = 10):
        self.max_context_messages = max_context_messages
        self.summary_threshold = summary_threshold
        self._summaries: list[dict[str, Any]] = []
        self._summary_turns: list[int] = []  # Turn numbers when summaries were created

    def should_summarize(self, conversation_length: int, turn_number: int) -> bool:
        """Check if context should be summarized."""
        # Summarize when approaching max context
        if conversation_length >= self.max_context_messages * 0.8:
            return True

        # Summarize every N turns
        if self._summary_turns and (turn_number - self._summary_turns[-1]) >= self.summary_threshold:
            return True

        return False

    def create_summary(
        self,
        conversation: list[dict[str, Any]],
        actions: list[Any],
        turn_number: int,
    ) -> dict[str, Any]:
        """Create a summary of the conversation so far."""
        # Identify key information to preserve
        summary = {
            "turn_number": turn_number,
            "timestamp": time.time(),
            "files_modified": self._extract_modified_files(actions),
            "key_decisions": self._extract_key_decisions(conversation),
            "active_context": self._extract_active_context(conversation),
            "pending_tasks": self._extract_pending_tasks(conversation),
            "summary_text": self._generate_summary_text(conversation, actions),
        }

        self._summaries.append(summary)
        self._summary_turns.append(turn_number)

        return summary

    def _extract_modified_files(self, actions: list[Any]) -> list[str]:
        """Extract files that were modified."""
        files = set()
        for action in actions:
            if hasattr(action, "action") and action.action in {"created", "modified"}:
                if hasattr(action, "target"):
                    files.add(str(action.target))
        return sorted(files)

    def _extract_key_decisions(self, conversation: list[dict[str, Any]]) -> list[str]:
        """Extract key decisions from conversation."""
        decisions = []
        for msg in conversation[-20:]:  # Look at recent messages
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                # Look for decision indicators
                if any(
                    phrase in content.lower()
                    for phrase in ["decided to", "will now", "implementing", "chose to", "using"]
                ):
                    decisions.append(content[:200])
        return decisions[:5]  # Limit to 5 key decisions

    def _extract_active_context(self, conversation: list[dict[str, Any]]) -> list[str]:
        """Extract currently active context (files, concepts being discussed)."""
        context = []
        for msg in conversation[-10:]:
            content = msg.get("content", "")
            # Look for file references
            import re

            file_refs = re.findall(r"[\w./\-]+\.py|[\w./\-]+\.js|[\w./\-]+\.ts", content)
            context.extend(file_refs)
        return list(set(context))[:10]

    def _extract_pending_tasks(self, conversation: list[dict[str, Any]]) -> list[str]:
        """Extract pending tasks or TODOs mentioned."""
        tasks = []
        for msg in conversation[-15:]:
            content = msg.get("content", "")
            if any(phrase in content.lower() for phrase in ["todo", "to do", "next", "pending", "still need"]):
                tasks.append(content[:150])
        return tasks[:5]

    def _generate_summary_text(self, conversation: list[dict[str, Any]], actions: list[Any]) -> str:
        """Generate a natural language summary."""
        modified = self._extract_modified_files(actions)
        context = self._extract_active_context(conversation)

        parts = []

        if modified:
            parts.append(f"Modified files: {', '.join(modified)}")

        if context:
            parts.append(f"Active context: {', '.join(context)}")

        # Count tool usage
        tool_counts: dict[str, int] = {}
        for action in actions[-20:]:
            if hasattr(action, "details"):
                details = action.details or {}
                tool = details.get("tool")
                if tool:
                    tool_counts[tool] = tool_counts.get(tool, 0) + 1

        if tool_counts:
            tools_str = ", ".join(f"{k}×{v}" for k, v in sorted(tool_counts.items(), key=lambda x: -x[1])[:5])
            parts.append(f"Recent tools: {tools_str}")

        return " | ".join(parts) if parts else "No significant changes"

    def get_summary_prompt(self) -> str:
        """Get a prompt summarizing previous context."""
        if not self._summaries:
            return ""

        parts = ["## Previous Session Summary"]

        for summary in self._summaries[-3:]:  # Last 3 summaries
            parts.append(f"\n### Turn {summary['turn_number']}")
            parts.append(summary["summary_text"])

            if summary["files_modified"]:
                parts.append(f"- Modified: {', '.join(summary['files_modified'])}")

        return "\n".join(parts)

    def prune_conversation(
        self,
        conversation: list[dict[str, Any]],
        system_message: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Prune conversation while preserving important messages.

        Returns pruned conversation with system message at start.
        """
        if len(conversation) <= self.max_context_messages:
            return conversation

        # Always keep system message
        messages = [system_message]

        # Score remaining messages
        scored = self._score_messages(conversation[1:])  # Skip system message

        # Sort by score and keep top messages
        scored.sort(key=lambda x: x.total_score, reverse=True)
        keep_count = self.max_context_messages - 1  # Reserve space for system
        to_keep = scored[:keep_count]

        # Restore original order
        to_keep.sort(key=lambda x: x.message_index)

        for scored_msg in to_keep:
            messages.append(conversation[1 + scored_msg.message_index])

        return messages

    def _score_messages(self, messages: list[dict[str, Any]]) -> list[MessageScore]:
        """Score messages for importance."""
        scored = []
        now = time.time()

        for i, msg in enumerate(messages):
            # Recency score (exponential decay)
            recency_score = 1.0 / (1.0 + (len(messages) - i) * 0.1)

            # Importance based on content
            importance_score = self._calculate_importance_score(msg)

            # Tool result score
            tool_result_score = self._calculate_tool_result_score(msg)

            total = recency_score * 0.3 + importance_score * 0.5 + tool_result_score * 0.2

            scored.append(MessageScore(
                message_index=i,
                recency_score=recency_score,
                importance_score=importance_score,
                tool_result_score=tool_result_score,
                total_score=total,
            ))

        return scored

    def _calculate_importance_score(self, message: dict[str, Any]) -> float:
        """Calculate importance score for a message."""
        content = message.get("content", "")
        score = 0.5  # Base score

        # User questions are important
        if "?" in content:
            score += 0.2

        # Code blocks are important
        if "```" in content:
            score += 0.2

        # Error messages are important
        if any(word in content.lower() for word in ["error", "failed", "exception", "bug"]):
            score += 0.3

        # Decisions are important
        if any(phrase in content.lower() for phrase in ["decided", "will", "should", "must"]):
            score += 0.1

        return min(1.0, score)

    def _calculate_tool_result_score(self, message: dict[str, Any]) -> float:
        """Calculate score based on tool results."""
        if message.get("role") != "tool":
            return 0.0

        # Tool results with errors are important
        content = message.get("content", "")
        if any(word in content.lower() for word in ["error", "failed", "exception"]):
            return 1.0

        # Successful tool results are moderately important
        return 0.5


class SmartContextManager:
    """Manages conversation context with intelligent pruning."""

    def __init__(
        self,
        max_context_messages: int = 40,
        max_tokens: int = 8000,
        summary_threshold: int = 10,
    ):
        self.max_context_messages = max_context_messages
        self.max_tokens = max_tokens
        self.summarizer = ContextSummarizer(
            max_context_messages=max_context_messages,
            summary_threshold=summary_threshold,
        )
        self._token_counts: list[int] = []

    def add_message(
        self,
        conversation: list[dict[str, Any]],
        message: dict[str, Any],
        turn_number: int,
        actions: Optional[list[Any]] = None,
    ) -> list[dict[str, Any]]:
        """Add a message and manage context."""
        conversation.append(message)

        # Check if summarization needed
        if self.summarizer.should_summarize(len(conversation), turn_number):
            if actions is not None:
                self.summarizer.create_summary(conversation, actions, turn_number)

        # Prune if over limit
        if len(conversation) > self.max_context_messages:
            system_message = conversation[0]
            conversation = self.summarizer.prune_conversation(conversation, system_message)

        return conversation

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        # Rough estimate: 1 token ≈ 4 characters
        return len(text) // 4

    def get_context_summary(self) -> str:
        """Get current context summary."""
        return self.summarizer.get_summary_prompt()


def create_context_manager(
    max_context_messages: int = 40,
    max_tokens: int = 8000,
) -> SmartContextManager:
    """Create a context manager instance."""
    return SmartContextManager(
        max_context_messages=max_context_messages,
        max_tokens=max_tokens,
    )
