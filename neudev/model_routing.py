"""Model capability presets and automatic routing for NeuDev."""

from __future__ import annotations

from dataclasses import dataclass


LEGACY_DEFAULT_MODEL = "qwen3:latest"  # Current recommended default model


# Keep backward compatibility for old qwen3.5 references


@dataclass(frozen=True)
class ModelTraits:
    family: str
    role_label: str
    coding: float
    reasoning: float
    tool_use: float
    chat_capable: bool
    supports_thinking: bool
    stable_thinking: bool


@dataclass(frozen=True)
class AgentTeam:
    planner: str
    executor: str
    reviewer: str
    executor_candidates: tuple[str, ...]
    route_reason: str


@dataclass(frozen=True)
class TaskDecision:
    task_type: str
    route_reason: str
    stack_tags: tuple[str, ...] = ()


QWEN3_TRAITS = ModelTraits(
    family="qwen3",
    role_label="Planner / Reasoner",
    coding=9.3,
    reasoning=9.8,
    tool_use=9.7,
    chat_capable=True,
    supports_thinking=True,
    stable_thinking=True,
)


DEFAULT_TRAITS = ModelTraits(
    family="generic",
    role_label="General",
    coding=6.5,
    reasoning=6.5,
    tool_use=5.0,
    chat_capable=True,
    supports_thinking=False,
    stable_thinking=False,
)


MODEL_RULES: list[tuple[str, ModelTraits]] = [
    (
        "qwen3.5",
        QWEN3_TRAITS,
    ),
    (
        "qwen3",
        QWEN3_TRAITS,
    ),
    (
        "qwen2.5-coder",
        ModelTraits(
            family="qwen2.5-coder",
            role_label="Main Coder",
            coding=9.6,
            reasoning=8.4,
            tool_use=8.0,
            chat_capable=True,
            supports_thinking=True,
            stable_thinking=True,
        ),
    ),
    (
        "deepseek-coder-v2",
        ModelTraits(
            family="deepseek-coder-v2",
            role_label="Refactor Specialist",
            coding=9.9,
            reasoning=8.9,
            tool_use=7.2,
            chat_capable=True,
            supports_thinking=True,
            stable_thinking=False,
        ),
    ),
    (
        "deepseek-coder",
        ModelTraits(
            family="deepseek-coder",
            role_label="Debug Coder",
            coding=9.2,
            reasoning=7.8,
            tool_use=6.3,
            chat_capable=True,
            supports_thinking=True,
            stable_thinking=False,
        ),
    ),
    (
        "codellama",
        ModelTraits(
            family="codellama",
            role_label="Legacy Coder",
            coding=7.6,
            reasoning=6.1,
            tool_use=4.8,
            chat_capable=True,
            supports_thinking=False,
            stable_thinking=False,
        ),
    ),
    (
        "starcoder2",
        ModelTraits(
            family="starcoder2",
            role_label="Quick Edit Coder",
            coding=7.1,
            reasoning=5.8,
            tool_use=0.0,
            chat_capable=True,
            supports_thinking=False,
            stable_thinking=False,
        ),
    ),
    (
        "nomic-embed-text",
        ModelTraits(
            family="nomic-embed-text",
            role_label="Embeddings Only",
            coding=0.0,
            reasoning=0.0,
            tool_use=0.0,
            chat_capable=False,
            supports_thinking=False,
            stable_thinking=False,
        ),
    ),
]

PLANNING_KEYWORDS = {
    "analyze",
    "analysis",
    "deeply",
    "understand",
    "investigate",
    "review",
    "architecture",
    "explain",
    "plan",
    "reason",
    "repository",
    "project",
    "repo",
    "workflow",
    "agent",
}
CODING_KEYWORDS = {
    "write",
    "implement",
    "create",
    "build",
    "complete",
    "generate",
    "function",
    "class",
    "script",
    "code",
    "feature",
    "endpoint",
    "component",
    "page",
    "route",
    "layout",
    "ui",
    "website",
    "frontend",
}
REFACTOR_KEYWORDS = {
    "refactor",
    "restructure",
    "overhaul",
    "migrate",
    "rename across",
    "large change",
    "major change",
    "multi-file",
    "cross-file",
    "cleanup architecture",
}
DEBUG_KEYWORDS = {
    "debug",
    "fix",
    "issue",
    "problem",
    "bug",
    "error",
    "traceback",
    "failing",
    "broken",
    "why",
    "crash",
    "exception",
}
QUICK_EDIT_KEYWORDS = {
    "quick edit",
    "small edit",
    "minor edit",
    "tiny fix",
    "one-line",
    "simple change",
    "small change",
    "quick fix",
    "typo",
}
SEARCH_KEYWORDS = {
    "search",
    "find",
    "locate",
    "where is",
    "grep",
    "symbol",
    "reference",
    "usage",
    "code search",
    "look up",
}
# Website creation is a complex multi-file task that needs strong coding ability
WEBSITE_KEYWORDS = {
    "website",
    "web page",
    "landing page",
    "single page",
    "html",
    "css",
    "javascript",
    "responsive",
    "travel website",
    "portfolio",
    "blog",
}
STACK_HINTS: list[tuple[str, set[str]]] = [
    ("React", {"react", "next.js", "nextjs", "jsx", "tsx", "vite"}),
    ("TypeScript", {"typescript", "tsx", ".ts", "tsconfig"}),
    ("Flutter", {"flutter", "pubspec", "widget tree", "riverpod", "flutter_bloc"}),
    ("Dart", {"dart"}),
    ("Python", {"python", "pyproject", "requirements.txt", "pytest"}),
    ("FastAPI", {"fastapi", "uvicorn", "starlette"}),
]


def get_model_traits(model_name: str) -> ModelTraits:
    """Return the closest capability profile for a model name."""
    lowered = model_name.lower()
    for pattern, traits in MODEL_RULES:
        if pattern in lowered:
            return traits
    return DEFAULT_TRAITS


def get_model_role_label(model_name: str) -> str:
    """Human-friendly description for the model picker."""
    return get_model_traits(model_name).role_label


def is_chat_capable_model(model_name: str) -> bool:
    """Return whether a model can be used for the interactive chat agent."""
    return get_model_traits(model_name).chat_capable


def should_enable_thinking(model_name: str, requested: bool) -> bool:
    """Enable visible model reasoning only for profiles that are stable enough."""
    if not requested:
        return False
    traits = get_model_traits(model_name)
    return traits.supports_thinking and traits.stable_thinking


def rank_models(
    models: list[dict],
    messages: list[dict],
    has_tools: bool,
    gpu_vram_gb: int = 16,
) -> tuple[list[dict], str]:
    """Rank installed models for the current task."""
    task = _classify_task(_latest_user_message(messages), has_tools)
    stack_tags = _detect_stack_tags(messages)
    route_reason = _describe_route(task.route_reason, stack_tags)

    ranked = []
    for model in models:
        name = model.get("name", "unknown")
        traits = get_model_traits(name)
        if not traits.chat_capable:
            continue

        enriched = dict(model)
        enriched["role"] = traits.role_label
        enriched["score"] = round(
            _score_model_for_task(
                name, traits, task.task_type, has_tools, stack_tags,
                model_size_bytes=model.get("size", 0),
                gpu_vram_gb=gpu_vram_gb,
            ),
            3,
        )
        ranked.append(enriched)

    ranked.sort(
        key=lambda item: (item["score"], item.get("size", 0), item["name"]),
        reverse=True,
    )
    return ranked, route_reason


def preview_best_model(
    models: list[dict],
    messages: list[dict],
    has_tools: bool,
) -> tuple[str | None, str]:
    """Return the best model name and a short explanation."""
    if not models:
        return None, "no models available"

    ranked, reason = rank_models(models, messages, has_tools)
    if not ranked:
        return None, "no chat-capable models available"
    return ranked[0]["name"], reason


def build_agent_team(models: list[dict], messages: list[dict], has_tools: bool) -> AgentTeam:
    """Choose planner, executor, and reviewer roles from installed models."""
    chat_models = [model for model in models if is_chat_capable_model(model.get("name", ""))]
    if not chat_models:
        raise ValueError("No chat-capable models are available for team selection.")

    task = _classify_task(_latest_user_message(messages), has_tools)
    stack_tags = _detect_stack_tags(messages)
    executor_ranked, route_reason = rank_models(chat_models, messages, has_tools)
    executor = executor_ranked[0]["name"]

    planner = _rank_specialist(
        chat_models,
        role="planner",
        task_type=task.task_type,
        has_tools=has_tools,
        stack_tags=stack_tags,
    )[0]["name"]

    reviewer_ranked = _rank_specialist(
        chat_models,
        role="reviewer",
        task_type=task.task_type,
        has_tools=has_tools,
        stack_tags=stack_tags,
    )
    reviewer = reviewer_ranked[0]["name"]
    for candidate in reviewer_ranked:
        if candidate["name"] != executor:
            reviewer = candidate["name"]
            break

    executor_candidates: list[str] = []
    for candidate in executor_ranked:
        name = candidate["name"]
        if name not in executor_candidates:
            executor_candidates.append(name)
        if len(executor_candidates) >= 4:
            break

    if planner not in executor_candidates:
        executor_candidates.append(planner)

    return AgentTeam(
        planner=planner,
        executor=executor,
        reviewer=reviewer,
        executor_candidates=tuple(executor_candidates),
        route_reason=route_reason,
    )


def _latest_user_message(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _classify_task(user_text: str, has_tools: bool) -> TaskDecision:
    """
    Classify the task type using weighted keyword matching.

    Improvements:
    - Position-weighted scoring (earlier keywords matter more)
    - Phrase boosting for multi-word indicators
    - Hybrid task detection with confidence scoring
    - Website creation detection for complex multi-file tasks
    """
    text = user_text.lower()
    words = text.split()

    # Base keyword hits
    planning_hits = _keyword_hits(text, PLANNING_KEYWORDS)
    coding_hits = _keyword_hits(text, CODING_KEYWORDS)
    refactor_hits = _keyword_hits(text, REFACTOR_KEYWORDS)
    debug_hits = _keyword_hits(text, DEBUG_KEYWORDS)
    quick_hits = _keyword_hits(text, QUICK_EDIT_KEYWORDS)
    search_hits = _keyword_hits(text, SEARCH_KEYWORDS)
    website_hits = _keyword_hits(text, WEBSITE_KEYWORDS)

    # Position-weighted bonus: keywords in first 5 words get 1.5x multiplier
    first_words = set(words[:5])
    position_bonus = {
        "planning": sum(1.5 for w in first_words if w in PLANNING_KEYWORDS),
        "coding": sum(1.5 for w in first_words if w in CODING_KEYWORDS),
        "refactor": sum(1.5 for w in first_words if w in REFACTOR_KEYWORDS),
        "debug": sum(1.5 for w in first_words if w in DEBUG_KEYWORDS),
        "website": sum(1.5 for w in first_words if w in WEBSITE_KEYWORDS),
    }

    # Phrase boosting: detect multi-word patterns
    phrase_boost = 0.0
    if "analyze" in text and ("build" in text or "implement" in text or "create" in text):
        phrase_boost = 2.0  # Strong hybrid signal
    elif "refactor" in text and ("improve" in text or "clean" in text):
        phrase_boost = 1.5
    elif "fix" in text and ("bug" in text or "issue" in text or "error" in text):
        phrase_boost = 1.5

    # Website creation is a complex multi-file task - boost it high
    website_score = (website_hits * 2.5) + position_bonus["website"]
    if website_hits >= 2:
        website_score += 5.0  # Strong signal for website creation

    # Weighted scoring with position bonuses
    scores: dict[str, float] = {
        "complex_refactor": (refactor_hits * 2.0) + position_bonus["refactor"],
        "quick_edit": quick_hits * 2.5,
        "planning": (planning_hits * 1.5) + position_bonus["planning"],
        "main_coding": (coding_hits * 1.2) + position_bonus["coding"],
        "debugging": (debug_hits * 1.3) + position_bonus["debug"] + phrase_boost,
        "code_search": search_hits * 1.0,
        "website_creation": website_score,
    }

    # Mixed planning+coding → dedicated hybrid type with phrase boost
    if planning_hits and coding_hits:
        hybrid_score = (planning_hits + coding_hits) * 1.4 + phrase_boost
        # Boost further if both appear in first 5 words
        if position_bonus["planning"] > 0 and position_bonus["coding"] > 0:
            hybrid_score += 3.0
        scores["analysis_implementation"] = hybrid_score
    elif phrase_boost > 0 and "analysis_implementation" not in scores:
        # Apply phrase boost to most likely category
        if planning_hits > coding_hits:
            scores["planning"] += phrase_boost
        elif coding_hits > 0:
            scores["main_coding"] += phrase_boost

    best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_type]

    if best_score <= 0:
        if has_tools:
            return TaskDecision("general", "tool-heavy workspace task")
        return TaskDecision("general", "general assistant task")

    REASON_MAP = {
        "complex_refactor": "complex refactor and cross-file changes",
        "quick_edit": "quick edits and small code changes",
        "analysis_implementation": "deep analysis followed by implementation",
        "planning": "deep analysis and workspace reasoning" if has_tools else "planning and reasoning",
        "debugging": "debugging and bug fixing",
        "main_coding": "code generation and editing",
        "code_search": "code search and repository navigation",
        "website_creation": "website creation with HTML/CSS/JS - complex multi-file implementation",
    }
    return TaskDecision(best_type, REASON_MAP.get(best_type, "general task"))


def _keyword_hits(text: str, keywords: set[str]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _score_model_for_task(
    model_name: str,
    traits: ModelTraits,
    task_type: str,
    has_tools: bool,
    stack_tags: tuple[str, ...],
    model_size_bytes: int = 0,
    gpu_vram_gb: int = 16,
) -> float:
    order = _task_preference_order(task_type, has_tools)
    index = _family_priority(traits.family, order)
    score = 18.0 if index is None else 120.0 - (index * 12.0)

    coding_weight, reasoning_weight, tool_weight = _task_trait_weights(task_type, has_tools)
    score += traits.coding * coding_weight
    score += traits.reasoning * reasoning_weight
    score += traits.tool_use * tool_weight

    if has_tools and traits.tool_use < 5.5:
        score -= 10.0
    if task_type in {"planning", "code_search", "general"} and has_tools and traits.tool_use < 7.0:
        score -= 4.0
    if task_type == "analysis_implementation" and has_tools and traits.family == "qwen3":
        score += 2.5
    if task_type == "quick_edit" and not has_tools and traits.family == "starcoder2":
        score += 4.0
    if task_type == "complex_refactor" and traits.family == "deepseek-coder-v2":
        score += 6.0
    if task_type == "debugging" and not has_tools and traits.family == "deepseek-coder":
        score += 3.0
    if task_type == "debugging" and has_tools and traits.family == "qwen3":
        score += 4.0
    score += _stack_bonus(traits.family, task_type, stack_tags, has_tools)
    if model_name.endswith(":latest"):
        score += 0.15

    # VRAM-aware penalty: avoid loading models that consume >70% of GPU memory
    score += _vram_penalty(model_size_bytes, gpu_vram_gb)

    return score


def _task_preference_order(task_type: str, has_tools: bool) -> tuple[str, ...]:
    if task_type == "planning":
        return ("qwen3", "deepseek-coder-v2", "qwen2.5-coder", "deepseek-coder", "codellama", "starcoder2")
    if task_type == "analysis_implementation":
        # For complex multi-step tasks, prefer stronger models
        return ("deepseek-coder-v2", "qwen2.5-coder", "qwen3", "deepseek-coder", "starcoder2", "codellama")
    if task_type == "main_coding":
        # For substantial coding tasks (websites, features), prefer deepseek-coder-v2 for better quality
        return ("deepseek-coder-v2", "qwen2.5-coder", "qwen3", "deepseek-coder", "starcoder2", "codellama")
    if task_type == "website_creation":
        # Website creation needs strong multi-file coding - use best coding model
        return ("deepseek-coder-v2", "qwen2.5-coder", "qwen3", "deepseek-coder", "starcoder2", "codellama")
    if task_type == "complex_refactor":
        return ("deepseek-coder-v2", "qwen3", "qwen2.5-coder", "deepseek-coder", "codellama", "starcoder2")
    if task_type == "debugging":
        if has_tools:
            return ("qwen3", "deepseek-coder-v2", "deepseek-coder", "qwen2.5-coder", "starcoder2", "codellama")
        return ("deepseek-coder", "deepseek-coder-v2", "qwen3", "qwen2.5-coder", "starcoder2", "codellama")
    if task_type == "quick_edit":
        if has_tools:
            return ("qwen2.5-coder", "qwen3", "starcoder2", "deepseek-coder", "codellama")
        return ("starcoder2", "qwen2.5-coder", "qwen3", "deepseek-coder", "codellama")
    if task_type == "code_search":
        return ("qwen3", "qwen2.5-coder", "deepseek-coder-v2", "deepseek-coder", "codellama", "starcoder2")
    if has_tools:
        return ("qwen3", "qwen2.5-coder", "deepseek-coder-v2", "deepseek-coder", "codellama", "starcoder2")
    return ("qwen3", "qwen2.5-coder", "deepseek-coder-v2", "deepseek-coder", "starcoder2", "codellama")


def _task_trait_weights(task_type: str, has_tools: bool) -> tuple[float, float, float]:
    """
    Return trait weights (coding, reasoning, tool_use) for a task type.

    Fix: Explicit parentheses to ensure correct ternary operator precedence.
    Without parentheses, the expression `a if cond else b, c, d` is parsed as
    `(a if cond else b), c, d` which returns wrong tuples.
    """
    if task_type == "planning":
        return (0.5, 1.8, (1.5 if has_tools else 0.4))
    if task_type == "analysis_implementation":
        return (1.7, 1.3, (1.1 if has_tools else 0.3))
    if task_type == "main_coding":
        return (1.9, 0.8, (0.8 if has_tools else 0.2))
    if task_type == "website_creation":
        # Website creation needs strong coding ability with multi-file coordination
        return (2.0, 0.9, (0.9 if has_tools else 0.3))
    if task_type == "complex_refactor":
        return (1.7, 1.5, (0.8 if has_tools else 0.2))
    if task_type == "debugging":
        return (1.5, 1.4, (1.0 if has_tools else 0.3))
    if task_type == "quick_edit":
        return (1.4, 0.6, (0.7 if has_tools else 0.0))
    if task_type == "code_search":
        return (0.9, 1.4, (1.7 if has_tools else 0.3))
    return (1.0, 1.2, (1.2 if has_tools else 0.0))


def _vram_penalty(model_size_bytes: int, gpu_vram_gb: int = 16) -> float:
    """Penalize models that would consume too much GPU memory."""
    if model_size_bytes <= 0:
        return 0.0
    model_gb = model_size_bytes / (1024 ** 3)
    if model_gb > gpu_vram_gb * 0.7:
        return -8.0
    if model_gb > gpu_vram_gb * 0.5:
        return -3.0
    return 0.0


def _family_priority(family: str, order: tuple[str, ...]) -> int | None:
    for index, preferred in enumerate(order):
        if family == preferred:
            return index
    return None


def _rank_specialist(
    models: list[dict],
    role: str,
    task_type: str,
    has_tools: bool,
    stack_tags: tuple[str, ...],
) -> list[dict]:
    ranked = []
    for model in models:
        name = model.get("name", "unknown")
        traits = get_model_traits(name)
        if not traits.chat_capable:
            continue

        if role == "planner":
            score = _score_model_for_task(name, traits, "planning", True, stack_tags)
            score += traits.reasoning * 1.5 + traits.tool_use * 0.8
        elif role == "reviewer":
            review_task = "complex_refactor" if task_type == "complex_refactor" else "planning"
            score = _score_model_for_task(name, traits, review_task, has_tools, stack_tags)
            score += traits.reasoning * 1.4 + traits.coding * 1.0 + traits.tool_use * (0.6 if has_tools else 0.2)
        else:
            score = _score_model_for_task(name, traits, task_type, has_tools, stack_tags)

        if name.endswith(":latest"):
            score += 0.15

        enriched = dict(model)
        enriched["score"] = round(score, 3)
        ranked.append(enriched)

    ranked.sort(
        key=lambda item: (item["score"], item.get("size", 0), item["name"]),
        reverse=True,
    )
    return ranked


def _detect_stack_tags(messages: list[dict]) -> tuple[str, ...]:
    """Extract stack hints from system and user messages."""
    text = _context_text(messages)
    detected = []
    for tag, keywords in STACK_HINTS:
        if any(keyword in text for keyword in keywords):
            detected.append(tag)
    return tuple(detected)


def _context_text(messages: list[dict]) -> str:
    """Collect system and user context for stack-aware routing."""
    parts = []
    for message in messages[-8:]:
        if message.get("role") not in {"system", "user"}:
            continue
        parts.append(str(message.get("content", "")).lower())
    return "\n".join(parts)


def _describe_route(base_reason: str, stack_tags: tuple[str, ...]) -> str:
    """Append technology context to the route reason."""
    if not stack_tags:
        return base_reason
    return f"{base_reason} for {'/'.join(stack_tags[:3])} stack"


def _stack_bonus(family: str, task_type: str, stack_tags: tuple[str, ...], has_tools: bool) -> float:
    """Bias routing toward models that fit the active technology stack."""
    if not stack_tags:
        return 0.0

    tags = set(stack_tags)
    bonus = 0.0

    if {"React", "TypeScript"} & tags:
        if family == "qwen2.5-coder" and task_type in {"analysis_implementation", "main_coding", "quick_edit"}:
            bonus += 4.0
        if family == "deepseek-coder-v2" and task_type == "complex_refactor":
            bonus += 3.0
        if family == "qwen3" and task_type in {"planning", "analysis_implementation", "general", "code_search"}:
            bonus += 2.0

    if {"Flutter", "Dart"} & tags:
        if family == "qwen3" and task_type in {"planning", "debugging", "general"}:
            bonus += 2.8 if has_tools else 2.2
        if family == "qwen2.5-coder" and task_type in {"analysis_implementation", "main_coding", "quick_edit"}:
            bonus += 2.6
        if family == "deepseek-coder-v2" and task_type == "complex_refactor":
            bonus += 2.2

    if {"Python", "FastAPI"} & tags:
        if family == "qwen2.5-coder" and task_type in {"analysis_implementation", "main_coding", "quick_edit"}:
            bonus += 2.8
        if family == "deepseek-coder-v2" and task_type == "complex_refactor":
            bonus += 2.5
        if family == "deepseek-coder" and task_type == "debugging" and not has_tools:
            bonus += 2.4
        if family == "qwen3" and task_type in {"planning", "debugging", "general"}:
            bonus += 2.2 if has_tools else 1.6

    return bonus
