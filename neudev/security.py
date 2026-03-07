"""Secret detection and redaction for NeuDev security."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


# High-risk secret patterns
SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"(?i)(?:aws[_-]?)?(?:access[_-]?)?(?:key[_-]?)(?:id)?[:\s=]{0,3}[A-Z0-9]{16,}"),
    "aws_secret_key": re.compile(r"(?i)(?:aws[_-]?)?(?:secret[_-]?)?(?:access[_-]?)?(?:key)?[:\s=]{0,3}[A-Za-z0-9/+=]{30,}"),
    "github_token": re.compile(r"(?i)(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"),
    "github_pat": re.compile(r"(?i)github_pat_[A-Za-z0-9_]{22,}"),
    "gitlab_token": re.compile(r"(?i)glpat-[A-Za-z0-9\-]{20,}"),
    "slack_token": re.compile(r"(?i)xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*"),
    "slack_webhook": re.compile(r"(?i)https://hooks\.slack\.com/services/T[A-Z0-9]{8}/B[A-Z0-9]{8}/[A-Za-z0-9]{24}"),
    "stripe_key": re.compile(r"(?i)(?:sk|pk|rk)_(?:test|live)_[A-Za-z0-9]{24,}"),
    "stripe_restricted_key": re.compile(r"(?i)rk_live_[A-Za-z0-9]{24,}"),
    "pypi_token": re.compile(r"(?i)pypi-[A-Za-z0-9\-_]{100,}"),
    "npm_token": re.compile(r"(?i)//registry\.npmjs\.org/:_authToken=[A-Za-z0-9\-_]+"),
    "generic_api_key": re.compile(r"(?i)(?:api[_-]?key|apikey|api_secret)[:\s=]{0,3}[A-Za-z0-9\-_]{16,}"),
    "generic_secret": re.compile(r"(?i)(?:secret|password|passwd|pwd|token|auth)[:\s=]{0,3}[A-Za-z0-9\-_]{8,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "jwt_token": re.compile(r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"),
    "bearer_token": re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_\.]+"),
    "basic_auth": re.compile(r"(?i)basic\s+[A-Za-z0-9+/=]{20,}"),
    "connection_string": re.compile(r"(?i)(?:mongodb|postgres|mysql|redis|amqp)://[^\s\"']+:[^\s\"']+@[^\s\"']+"),
    "heroku_api_key": re.compile(r"(?i)heroku\.api\.key[:\s=]{0,3}[A-Fa-f0-9\-]{36}"),
    "twilio_api_key": re.compile(r"(?i)SK[0-9a-fA-F]{32}"),
    "sendgrid_api_key": re.compile(r"(?i)SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}"),
    "mailgun_api_key": re.compile(r"(?i)key-[A-Za-z0-9]{32}"),
    "google_api_key": re.compile(r"(?i)AIza[0-9A-Za-z\-_]{35}"),
    "google_oauth": re.compile(r"(?i)[0-9]+-[A-Za-z0-9_]{32}\.apps\.googleusercontent\.com"),
    "azure_storage_key": re.compile(r"(?i)DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]{88}"),
    "ssh_password": re.compile(r"(?i)sshpass\s+-p\s+['\"][^'\"]+['\"]"),
}

# Entropy-based secret detection
ENTROPY_THRESHOLD = 4.5
MIN_SECRET_LENGTH = 16
MAX_SECRET_LENGTH = 256


@dataclass
class SecretFinding:
    """Represents a detected secret."""

    secret_type: str
    pattern_name: str
    start_index: int
    end_index: int
    redacted_value: str
    confidence: float  # 0.0 to 1.0


class SecretDetector:
    """Detects and redacts secrets in text."""

    def __init__(
        self,
        enable_pattern_detection: bool = True,
        enable_entropy_detection: bool = True,
        min_entropy: float = ENTROPY_THRESHOLD,
    ):
        self.enable_pattern_detection = enable_pattern_detection
        self.enable_entropy_detection = enable_entropy_detection
        self.min_entropy = min_entropy
        self._findings: list[SecretFinding] = []

    def calculate_entropy(self, data: str) -> float:
        """Calculate Shannon entropy of a string."""
        if not data:
            return 0.0

        entropy = 0.0
        length = len(data)
        char_count: dict[str, int] = {}

        for char in data:
            char_count[char] = char_count.get(char, 0) + 1

        for count in char_count.values():
            probability = count / length
            if probability > 0:
                entropy -= probability * math.log2(probability)

        return entropy

    def is_high_entropy(self, value: str) -> bool:
        """Check if a string has high entropy (likely a secret)."""
        if len(value) < MIN_SECRET_LENGTH or len(value) > MAX_SECRET_LENGTH:
            return False

        # Check character distribution
        has_upper = any(c.isupper() for c in value)
        has_lower = any(c.islower() for c in value)
        has_digit = any(c.isdigit() for c in value)
        has_special = any(c in "-_=+/" for c in value)

        char_variety = sum([has_upper, has_lower, has_digit, has_special])
        if char_variety < 2:
            return False

        entropy = self.calculate_entropy(value)
        return entropy >= self.min_entropy

    def detect_secrets(self, text: str) -> list[SecretFinding]:
        """Detect secrets in text using pattern matching and entropy analysis."""
        self._findings = []

        if self.enable_pattern_detection:
            self._detect_pattern_secrets(text)

        if self.enable_entropy_detection:
            self._detect_entropy_secrets(text)

        # Sort by start index and remove overlaps
        self._findings.sort(key=lambda f: f.start_index)
        self._remove_overlaps()

        return self._findings

    def _detect_pattern_secrets(self, text: str) -> None:
        """Detect secrets using regex patterns."""
        for pattern_name, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                secret_value = match.group(0)
                # Extract the actual secret (after the label)
                if ":" in secret_value or "=" in secret_value:
                    secret_value = re.split(r"[:\s=]", secret_value, maxsplit=1)[-1].strip()

                confidence = self._calculate_pattern_confidence(pattern_name, secret_value)
                self._findings.append(SecretFinding(
                    secret_type=self._get_secret_type(pattern_name),
                    pattern_name=pattern_name,
                    start_index=match.start(),
                    end_index=match.end(),
                    redacted_value=self._redact_value(secret_value),
                    confidence=confidence,
                ))

    def _detect_entropy_secrets(self, text: str) -> None:
        """Detect secrets using entropy analysis."""
        # Find potential key-value pairs
        kv_pattern = re.compile(r'(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(?P<value>[A-Za-z0-9\-_+/]{16,256})')

        for match in kv_pattern.finditer(text):
            key = match.group("key").lower()
            value = match.group("value")

            # Skip if already detected by pattern matching
            if any(f.start_index <= match.start() < f.end_index for f in self._findings):
                continue

            # Check if key suggests a secret
            is_sensitive_key = any(term in key for term in ["key", "secret", "token", "password", "auth", "api"])

            if is_sensitive_key or self.is_high_entropy(value):
                confidence = 0.9 if is_sensitive_key else 0.7
                if self.is_high_entropy(value):
                    confidence = min(1.0, confidence + 0.1)

                self._findings.append(SecretFinding(
                    secret_type="generic_secret" if is_sensitive_key else "high_entropy_string",
                    pattern_name="entropy_detection",
                    start_index=match.start(),
                    end_index=match.end(),
                    redacted_value=self._redact_value(value),
                    confidence=confidence,
                ))

    def _calculate_pattern_confidence(self, pattern_name: str, secret_value: str) -> float:
        """Calculate confidence score for a pattern match."""
        base_confidence = 0.8

        # High confidence patterns
        if pattern_name in {"private_key", "jwt_token", "aws_access_key", "github_token"}:
            base_confidence = 0.95
        elif pattern_name in {"stripe_key", "connection_string"}:
            base_confidence = 0.9

        # Adjust based on value characteristics
        if len(secret_value) > 32:
            base_confidence = min(1.0, base_confidence + 0.05)
        if self.is_high_entropy(secret_value):
            base_confidence = min(1.0, base_confidence + 0.05)

        return base_confidence

    def _get_secret_type(self, pattern_name: str) -> str:
        """Map pattern name to secret type."""
        type_map = {
            "aws_access_key": "AWS Access Key",
            "aws_secret_key": "AWS Secret Key",
            "github_token": "GitHub Token",
            "github_pat": "GitHub Personal Access Token",
            "gitlab_token": "GitLab Token",
            "slack_token": "Slack Token",
            "slack_webhook": "Slack Webhook",
            "stripe_key": "Stripe API Key",
            "pypi_token": "PyPI Token",
            "npm_token": "NPM Token",
            "private_key": "Private Key",
            "jwt_token": "JWT Token",
            "connection_string": "Database Connection String",
            "google_api_key": "Google API Key",
            "azure_storage_key": "Azure Storage Key",
        }
        return type_map.get(pattern_name, "API Key/Secret")

    def _redact_value(self, value: str, visible_chars: int = 4) -> str:
        """Redact a secret value, showing only first few characters."""
        if len(value) <= visible_chars * 2:
            return "*" * len(value)
        return value[:visible_chars] + "*" * (len(value) - visible_chars * 2) + value[-visible_chars:]

    def _remove_overlaps(self) -> None:
        """Remove overlapping findings, keeping the highest confidence."""
        if not self._findings:
            return

        filtered: list[SecretFinding] = []
        for finding in self._findings:
            overlaps = [
                f for f in filtered
                if not (finding.end_index <= f.start_index or finding.start_index >= f.end_index)
            ]

            if not overlaps:
                filtered.append(finding)
            elif all(f.confidence <= finding.confidence for f in overlaps):
                # Remove overlaps and add this one
                filtered = [f for f in filtered if f not in overlaps]
                filtered.append(finding)

        self._findings = filtered

    def redact_text(self, text: str, replacement: str = "[REDACTED]") -> str:
        """Redact all detected secrets from text."""
        if not self._findings:
            self.detect_secrets(text)

        if not self._findings:
            return text

        # Sort by start index in reverse order to replace from end to start
        sorted_findings = sorted(self._findings, key=lambda f: f.start_index, reverse=True)

        result = text
        for finding in sorted_findings:
            result = result[:finding.start_index] + replacement + result[finding.end_index:]

        return result

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of detected secrets."""
        if not self._findings:
            return {"total": 0, "by_type": {}, "high_confidence": 0}

        by_type: dict[str, int] = {}
        high_confidence = 0

        for finding in self._findings:
            by_type[finding.secret_type] = by_type.get(finding.secret_type, 0) + 1
            if finding.confidence >= 0.8:
                high_confidence += 1

        return {
            "total": len(self._findings),
            "by_type": by_type,
            "high_confidence": high_confidence,
            "max_confidence": max(f.confidence for f in self._findings),
        }


def redact_secrets_in_payload(payload: Any, detector: SecretDetector | None = None) -> Any:
    """Recursively redact secrets in a dictionary/list payload."""
    if detector is None:
        detector = SecretDetector()

    if isinstance(payload, str):
        findings = detector.detect_secrets(payload)
        if findings:
            return detector.redact_text(payload)
        return payload

    if isinstance(payload, dict):
        return {k: redact_secrets_in_payload(v, detector) for k, v in payload.items()}

    if isinstance(payload, list):
        return [redact_secrets_in_payload(item, detector) for item in payload]

    return payload


def check_secrets_in_text(text: str, fail_on_high_confidence: bool = False) -> tuple[bool, str]:
    """
    Check text for secrets and return (has_secrets, warning_message).

    Args:
        text: Text to check
        fail_on_high_confidence: If True, only return True for high-confidence secrets

    Returns:
        Tuple of (has_secrets, warning_message)
    """
    detector = SecretDetector()
    findings = detector.detect_secrets(text)

    if not findings:
        return False, ""

    high_confidence = [f for f in findings if f.confidence >= 0.8]

    if fail_on_high_confidence and not high_confidence:
        return False, ""

    secret_types = set(f.secret_type for f in findings)
    message = (
        f"⚠️  Warning: Detected {len(findings)} potential secret(s) in content: "
        f"{', '.join(secret_types)}. "
        "Consider removing sensitive data before sending to AI models."
    )

    return True, message
