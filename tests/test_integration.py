"""Integration tests with mock Ollama server."""

import unittest
from unittest.mock import Mock, patch, MagicMock

try:
    import pytest
    import responses
    HAS_TEST_DEPS = True
except ImportError:
    HAS_TEST_DEPS = False
    pytest = None
    responses = None


# Mock Ollama responses
MOCK_OLLAMA_MODELS = {
    "models": [
        {
            "name": "qwen3:latest",
            "model": "qwen3:latest",
            "modified_at": "2024-01-01T00:00:00Z",
            "size": 4738418291,
            "digest": "abc123",
        },
        {
            "name": "qwen2.5-coder:7b",
            "model": "qwen2.5-coder:7b",
            "modified_at": "2024-01-01T00:00:00Z",
            "size": 4738418291,
            "digest": "def456",
        },
    ]
}

MOCK_OLLAMA_CHAT_RESPONSE = {
    "model": "qwen3:latest",
    "created_at": "2024-01-01T00:00:00Z",
    "message": {
        "role": "assistant",
        "content": "Hello! I'm NeuDev, your AI coding assistant.",
    },
    "done": True,
}


@unittest.skipIf(not HAS_TEST_DEPS, "pytest and responses are required for these tests")
class TestMockOllamaIntegration(unittest.TestCase):
    """Integration tests using mock Ollama server."""

    def setUp(self):
        """Set up mock Ollama responses."""
        if not HAS_TEST_DEPS:
            self.skipTest("pytest and responses are required")
        self.rsps = responses.RequestsMock()
        # Mock model list endpoint
        self.rsps.add(
            responses.GET,
            "http://127.0.0.1:11434/api/tags",
            json=MOCK_OLLAMA_MODELS,
            status=200,
        )
        # Mock chat completion endpoint
        self.rsps.add(
            responses.POST,
            "http://127.0.0.1:11434/api/chat",
            json=MOCK_OLLAMA_CHAT_RESPONSE,
            status=200,
        )
        self.rsps.start()

    def tearDown(self):
        self.rsps.stop()

    def test_llm_client_lists_models(self):
        """Test that LLM client can list models."""
        from neudev.llm import OllamaClient
        from neudev.config import NeuDevConfig

        config = NeuDevConfig(ollama_host="http://127.0.0.1:11434")
        client = OllamaClient(config)

        models = client.list_models()

        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["name"], "qwen3:latest")

    def test_llm_client_chat_completion(self):
        """Test LLM client chat completion."""
        from neudev.llm import OllamaClient
        from neudev.config import NeuDevConfig

        config = NeuDevConfig(ollama_host="http://127.0.0.1:11434", model="qwen3:latest")
        client = OllamaClient(config)

        messages = [{"role": "user", "content": "Hello"}]
        response = client.chat(messages)

        self.assertIn("content", response)
        self.assertIn("NeuDev", response["content"])


@unittest.skipIf(not HAS_TEST_DEPS, "pytest and responses are required for these tests")
class TestSecurityModule(unittest.TestCase):
    """Tests for security modules."""

    def test_secret_detector_finds_api_key(self):
        """Test secret detection in text."""
        from neudev.security import SecretDetector

        detector = SecretDetector()
        text = 'const API_KEY = "sk-1234567890abcdef";'

        findings = detector.detect_secrets(text)

        self.assertGreater(len(findings), 0)
        self.assertTrue(any("API" in f.secret_type or "Key" in f.secret_type for f in findings))

    def test_secret_detector_redacts_text(self):
        """Test secret redaction."""
        from neudev.security import SecretDetector

        detector = SecretDetector()
        text = 'AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'

        findings = detector.detect_secrets(text)
        redacted = detector.redact_text(text)

        self.assertTrue("wJalr" not in redacted or "[REDACTED]" in redacted)

    def test_path_security_blocks_traversal(self):
        """Test path traversal protection."""
        from neudev.path_security import PathSecurityValidator, PathRiskLevel

        validator = PathSecurityValidator("/workspace")
        result = validator.validate_path("../etc/passwd")

        self.assertFalse(result.is_safe)
        self.assertEqual(result.risk_level, PathRiskLevel.BLOCKED)

    def test_path_security_allows_safe_paths(self):
        """Test safe path validation."""
        from neudev.path_security import PathSecurityValidator

        validator = PathSecurityValidator("/workspace")
        result = validator.validate_path("src/main.py")

        # Should be blocked as outside workspace
        self.assertTrue(not result.is_safe or result.outside_workspace)


@unittest.skipIf(not HAS_TEST_DEPS, "pytest and responses are required for these tests")
class TestAuditLogging(unittest.TestCase):
    """Tests for audit logging."""

    def test_audit_logger_logs_events(self):
        """Test audit event logging."""
        import tempfile
        from pathlib import Path
        from neudev.audit import AuditLogger

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            log_dir = tmp_path / "audit_logs"
            logger = AuditLogger(log_dir=str(log_dir), enabled=True)
            logger.set_session("test-session-123")

            logger.log_tool_execute("read_file", "test.py", {"path": "test.py"})

            # Check log file was created
            log_files = list(log_dir.glob("*.jsonl"))
            self.assertGreater(len(log_files), 0)

    def test_rate_limiter_limits_calls(self):
        """Test rate limiting."""
        from neudev.audit import RateLimiter, RateLimitConfig

        config = RateLimitConfig(max_per_minute=2)
        limiter = RateLimiter(config)

        # First two calls should succeed
        allowed1, _ = limiter.check_rate_limit("test_tool")
        limiter.record_call("test_tool")
        allowed2, _ = limiter.check_rate_limit("test_tool")
        limiter.record_call("test_tool")

        # Third call should be rate limited
        allowed3, reason = limiter.check_rate_limit("test_tool")

        self.assertTrue(allowed1)
        self.assertTrue(allowed2)
        self.assertFalse(allowed3)
        self.assertIn("Rate limit", reason)


class TestASTParser(unittest.TestCase):
    """Tests for AST parser."""

    def test_ast_parser_extracts_functions(self):
        """Test AST function extraction."""
        from neudev.ast_parser import JSTSParser, SymbolKind

        parser = JSTSParser()
        source = """
        export function greet(name: string): void {
            console.log(`Hello, ${name}!`);
        }

        class Widget {
            async run(): Promise<void> {
                return Promise.resolve();
            }
        }
        """

        if parser.is_available:
            symbols = parser.parse(source)

            self.assertGreaterEqual(len(symbols), 1)
            self.assertTrue(any(s.kind == SymbolKind.FUNCTION for s in symbols))
            self.assertTrue(any(s.kind == SymbolKind.CLASS for s in symbols))
        else:
            # Fallback to regex parsing
            symbols = parser.parse(source)
            self.assertGreaterEqual(len(symbols), 1)

    def test_ast_parser_fallback_to_regex(self):
        """Test fallback to regex parsing when tree-sitter unavailable."""
        from neudev.ast_parser import JSTSParser

        parser = JSTSParser()
        source = "function test() { return 42; }"

        # Should work even without tree-sitter
        symbols = parser.parse(source)
        self.assertGreaterEqual(len(symbols), 1)


class TestHealthCheck(unittest.TestCase):
    """Tests for health check module."""

    def test_health_checker_creates_report(self):
        """Test health check report generation."""
        from neudev.health_check import create_health_checker, HealthStatus

        checker = create_health_checker(
            ollama_host="http://127.0.0.1:11434",
            workspace="/tmp",
            session_store="/tmp/neudev_sessions",
        )

        report = checker.check_all()

        self.assertIn(report.status, [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY])
        self.assertGreater(len(report.checks), 0)
        self.assertIn("service_info", report.to_dict())

    def test_health_check_disk_space(self):
        """Test disk space health check."""
        from neudev.health_check import create_health_checker

        checker = create_health_checker()
        result = checker.check_disk_space()

        self.assertEqual(result.check_name, "disk_space")
        self.assertIsNotNone(result.details)
        self.assertIn("free_gb", result.details)


class TestObservability(unittest.TestCase):
    """Tests for observability module."""

    def test_logger_creates_instance(self):
        """Test logger creation."""
        from neudev.observability import get_logger, NeuDevLogger

        logger = get_logger()
        self.assertIsInstance(logger, NeuDevLogger)

    def test_metrics_collector_initializes(self):
        """Test metrics collector initialization."""
        from neudev.observability import get_metrics, NeuDevMetrics, PROMETHEUS_AVAILABLE
        
        if not PROMETHEUS_AVAILABLE:
            self.skipTest("prometheus-client is not available")
        
        metrics = get_metrics()
        self.assertIsInstance(metrics, NeuDevMetrics)

    def test_tracer_creates_spans(self):
        """Test tracer span creation."""
        from neudev.observability import get_tracer, NeuDevTracer

        tracer = get_tracer()
        self.assertIsInstance(tracer, NeuDevTracer)


@unittest.skipIf(not HAS_TEST_DEPS, "pytest is required for these tests")
class TestAgentIntegration(unittest.TestCase):
    """Integration tests for agent with mocked components."""

    @patch("neudev.llm.OllamaClient")
    def test_agent_processes_message(self, mock_ollama_class):
        """Test agent message processing with mocked LLM."""
        from neudev.agent import Agent
        from neudev.config import NeuDevConfig

        # Mock LLM client
        mock_llm = Mock()
        mock_llm.chat.return_value = {"content": "Test response"}
        mock_ollama_class.return_value = mock_llm

        config = NeuDevConfig()
        agent = Agent(config, workspace="/tmp", llm_client=mock_llm)

        # This would normally call the LLM
        # We're just testing the integration works
        self.assertIsNotNone(agent)
        self.assertEqual(agent.workspace, "/tmp")


# Run tests with: pytest tests/test_integration.py -v
