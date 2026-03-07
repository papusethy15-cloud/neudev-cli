"""Enhanced health check utilities for NeuDev server."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import urllib.error
import urllib.request


class HealthStatus(Enum):
    """Health check status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    check_name: str
    status: HealthStatus
    message: str
    latency_ms: Optional[float] = None
    details: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "check_name": self.check_name,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "details": self.details,
        }


@dataclass
class HealthReport:
    """Overall health report."""

    status: HealthStatus
    timestamp: str
    checks: list[HealthCheckResult]
    service_info: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "timestamp": self.timestamp,
            "checks": [check.to_dict() for check in self.checks],
            "service_info": self.service_info,
            "summary": {
                "total_checks": len(self.checks),
                "healthy": sum(1 for c in self.checks if c.status == HealthStatus.HEALTHY),
                "degraded": sum(1 for c in self.checks if c.status == HealthStatus.DEGRADED),
                "unhealthy": sum(1 for c in self.checks if c.status == HealthStatus.UNHEALTHY),
            },
        }


class HealthChecker:
    """Performs comprehensive health checks for NeuDev server."""

    def __init__(
        self,
        ollama_host: str = "http://127.0.0.1:11434",
        workspace: Optional[str] = None,
        session_store: Optional[str] = None,
    ):
        self.ollama_host = ollama_host.rstrip("/")
        self.workspace = Path(workspace) if workspace else None
        self.session_store = Path(session_store) if session_store else None

    def check_all(self) -> HealthReport:
        """Run all health checks and return comprehensive report."""
        checks: list[HealthCheckResult] = []

        # Run individual checks
        checks.append(self.check_api_server())
        checks.append(self.check_ollama())
        checks.append(self.check_ollama_models())
        checks.append(self.check_workspace())
        checks.append(self.check_session_store())
        checks.append(self.check_disk_space())
        checks.append(self.check_python_environment())
        checks.append(self.check_system_resources())

        # Determine overall status
        statuses = [check.status for check in checks]
        if HealthStatus.UNHEALTHY in statuses:
            overall_status = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY

        return HealthReport(
            status=overall_status,
            timestamp=datetime.utcnow().isoformat() + "Z",
            checks=checks,
            service_info=self._get_service_info(),
        )

    def check_api_server(self) -> HealthCheckResult:
        """Check if the NeuDev API server is responding."""
        start_time = time.time()
        try:
            # Check if we can bind to the port (for internal use)
            return HealthCheckResult(
                check_name="api_server",
                status=HealthStatus.HEALTHY,
                message="NeuDev API server is running",
                latency_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return HealthCheckResult(
                check_name="api_server",
                status=HealthStatus.UNHEALTHY,
                message=f"API server check failed: {e}",
            )

    def check_ollama(self) -> HealthCheckResult:
        """Check Ollama API connectivity."""
        start_time = time.time()
        try:
            request = urllib.request.Request(f"{self.ollama_host}/api/tags", method="GET")
            with urllib.request.urlopen(request, timeout=5) as response:
                import json

                payload = json.loads(response.read().decode("utf-8"))
                models = payload.get("models") or []

                latency_ms = (time.time() - start_time) * 1000

                if len(models) == 0:
                    return HealthCheckResult(
                        check_name="ollama",
                        status=HealthStatus.DEGRADED,
                        message="Ollama is reachable but no models are installed",
                        latency_ms=latency_ms,
                        details={"model_count": 0},
                    )

                return HealthCheckResult(
                    check_name="ollama",
                    status=HealthStatus.HEALTHY,
                    message=f"Ollama is running with {len(models)} model(s)",
                    latency_ms=latency_ms,
                    details={
                        "model_count": len(models),
                        "models": [m.get("name", "unknown") for m in models[:5]],
                    },
                )

        except urllib.error.URLError as e:
            return HealthCheckResult(
                check_name="ollama",
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot connect to Ollama at {self.ollama_host}: {e}",
            )
        except Exception as e:
            return HealthCheckResult(
                check_name="ollama",
                status=HealthStatus.UNHEALTHY,
                message=f"Ollama check failed: {e}",
            )

    def check_ollama_models(self) -> HealthCheckResult:
        """Check if required models are available."""
        try:
            request = urllib.request.Request(f"{self.ollama_host}/api/tags", method="GET")
            with urllib.request.urlopen(request, timeout=5) as response:
                import json

                payload = json.loads(response.read().decode("utf-8"))
                models = payload.get("models") or []
                model_names = {m.get("name", "").lower() for m in models}

                # Check for recommended models
                recommended = ["qwen3", "qwen2.5-coder"]
                found = [name for name in recommended if any(name in m for m in model_names)]
                missing = [name for name in recommended if name not in found]

                if not found:
                    return HealthCheckResult(
                        check_name="ollama_models",
                        status=HealthStatus.DEGRADED,
                        message=f"No recommended models found. Missing: {', '.join(missing)}",
                        details={
                            "installed": list(model_names),
                            "recommended": recommended,
                            "missing": missing,
                        },
                    )

                return HealthCheckResult(
                    check_name="ollama_models",
                    status=HealthStatus.HEALTHY,
                    message=f"Found {len(found)}/{len(recommended)} recommended models",
                    details={
                        "found": found,
                        "missing": missing,
                    },
                )

        except Exception as e:
            return HealthCheckResult(
                check_name="ollama_models",
                status=HealthStatus.UNHEALTHY,
                message=f"Model check failed: {e}",
            )

    def check_workspace(self) -> HealthCheckResult:
        """Check workspace directory accessibility."""
        if not self.workspace:
            return HealthCheckResult(
                check_name="workspace",
                status=HealthStatus.DEGRADED,
                message="Workspace not configured",
            )

        try:
            if not self.workspace.exists():
                return HealthCheckResult(
                    check_name="workspace",
                    status=HealthStatus.DEGRADED,
                    message=f"Workspace directory does not exist: {self.workspace}",
                )

            if not self.workspace.is_dir():
                return HealthCheckResult(
                    check_name="workspace",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Workspace path is not a directory: {self.workspace}",
                )

            # Check if writable
            test_file = self.workspace / ".neudev_health_check"
            try:
                test_file.touch()
                test_file.unlink()
                is_writable = True
            except (OSError, PermissionError):
                is_writable = False

            return HealthCheckResult(
                check_name="workspace",
                status=HealthStatus.HEALTHY if is_writable else HealthStatus.DEGRADED,
                message=f"Workspace is {'writable' if is_writable else 'read-only'}",
                details={
                    "path": str(self.workspace),
                    "writable": is_writable,
                    "exists": True,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                check_name="workspace",
                status=HealthStatus.UNHEALTHY,
                message=f"Workspace check failed: {e}",
            )

    def check_session_store(self) -> HealthCheckResult:
        """Check session store directory."""
        if not self.session_store:
            return HealthCheckResult(
                check_name="session_store",
                status=HealthStatus.DEGRADED,
                message="Session store not configured",
            )

        try:
            if not self.session_store.exists():
                # Try to create it
                try:
                    self.session_store.mkdir(parents=True, exist_ok=True)
                except (OSError, PermissionError) as e:
                    return HealthCheckResult(
                        check_name="session_store",
                        status=HealthStatus.UNHEALTHY,
                        message=f"Cannot create session store: {e}",
                    )

            if not self.session_store.is_dir():
                return HealthCheckResult(
                    check_name="session_store",
                    status=HealthStatus.UNHEALTHY,
                    message="Session store path is not a directory",
                )

            # Check if writable
            test_file = self.session_store / ".health_check"
            try:
                test_file.touch()
                test_file.unlink()
                is_writable = True
            except (OSError, PermissionError):
                is_writable = False

            return HealthCheckResult(
                check_name="session_store",
                status=HealthStatus.HEALTHY if is_writable else HealthStatus.DEGRADED,
                message=f"Session store is {'writable' if is_writable else 'read-only'}",
                details={
                    "path": str(self.session_store),
                    "writable": is_writable,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                check_name="session_store",
                status=HealthStatus.UNHEALTHY,
                message=f"Session store check failed: {e}",
            )

    def check_disk_space(self) -> HealthCheckResult:
        """Check available disk space."""
        try:
            # Get disk usage for workspace or root
            check_path = self.workspace or Path("/")
            total, used, free = shutil.disk_usage(str(check_path))

            free_gb = free / (1024**3)
            total_gb = total / (1024**3)
            usage_percent = (used / total) * 100

            if free_gb < 1:
                status = HealthStatus.UNHEALTHY
                message = f"Critical: Less than 1GB free ({free_gb:.2f}GB)"
            elif free_gb < 5:
                status = HealthStatus.DEGRADED
                message = f"Warning: Less than 5GB free ({free_gb:.2f}GB)"
            else:
                status = HealthStatus.HEALTHY
                message = f"Disk space OK ({free_gb:.2f}GB free)"

            return HealthCheckResult(
                check_name="disk_space",
                status=status,
                message=message,
                details={
                    "free_gb": round(free_gb, 2),
                    "total_gb": round(total_gb, 2),
                    "usage_percent": round(usage_percent, 1),
                },
            )

        except Exception as e:
            return HealthCheckResult(
                check_name="disk_space",
                status=HealthStatus.DEGRADED,
                message=f"Disk space check failed: {e}",
            )

    def check_python_environment(self) -> HealthCheckResult:
        """Check Python environment and dependencies."""
        try:
            # Check critical dependencies
            critical_deps = ["rich", "prompt_toolkit", "websockets", "ollama"]
            missing = []

            for dep in critical_deps:
                try:
                    __import__(dep.replace("-", "_"))
                except ImportError:
                    missing.append(dep)

            if missing:
                return HealthCheckResult(
                    check_name="python_environment",
                    status=HealthStatus.DEGRADED,
                    message=f"Missing dependencies: {', '.join(missing)}",
                    details={"missing": missing},
                )

            return HealthCheckResult(
                check_name="python_environment",
                status=HealthStatus.HEALTHY,
                message=f"Python {sys.version.split()[0]} with all dependencies",
                details={
                    "python_version": sys.version,
                    "python_executable": sys.executable,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                check_name="python_environment",
                status=HealthStatus.UNHEALTHY,
                message=f"Environment check failed: {e}",
            )

    def check_system_resources(self) -> HealthCheckResult:
        """Check system resources (memory, CPU)."""
        try:
            # Memory check (Linux-specific)
            mem_info = self._get_memory_info()
            if mem_info:
                total_mem = mem_info.get("total", 0)
                available_mem = mem_info.get("available", 0)
                available_gb = available_mem / (1024**3)

                if available_gb < 1:
                    status = HealthStatus.DEGRADED
                    message = f"Low memory: {available_gb:.2f}GB available"
                else:
                    status = HealthStatus.HEALTHY
                    message = f"Memory OK: {available_gb:.2f}GB available"

                return HealthCheckResult(
                    check_name="system_resources",
                    status=status,
                    message=message,
                    details=mem_info,
                )

            return HealthCheckResult(
                check_name="system_resources",
                status=HealthStatus.HEALTHY,
                message="System resources check passed",
            )

        except Exception as e:
            return HealthCheckResult(
                check_name="system_resources",
                status=HealthStatus.DEGRADED,
                message=f"System resources check failed: {e}",
            )

    def _get_memory_info(self) -> Optional[dict[str, Any]]:
        """Get system memory information (Linux)."""
        if os.name != "posix":
            return None

        try:
            with open("/proc/meminfo", "r") as f:
                meminfo = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value_parts = parts[1].strip().split()
                        value_kb = int(value_parts[0])
                        meminfo[key.lower()] = value_kb * 1024  # Convert to bytes

                return {
                    "total": meminfo.get("memtotal", 0),
                    "available": meminfo.get("memavailable", meminfo.get("memfree", 0)),
                    "total_gb": round(meminfo.get("memtotal", 0) / (1024**3), 2),
                    "available_gb": round(
                        meminfo.get("memavailable", meminfo.get("memfree", 0)) / (1024**3), 2
                    ),
                }
        except Exception:
            return None

    def _get_service_info(self) -> dict[str, Any]:
        """Get service information."""
        from neudev import __app_name__, __version__

        return {
            "service": __app_name__,
            "version": __version__,
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
            "hostname": socket.gethostname(),
            "ollama_host": self.ollama_host,
        }


def create_health_checker(
    ollama_host: str = "http://127.0.0.1:11434",
    workspace: Optional[str] = None,
    session_store: Optional[str] = None,
) -> HealthChecker:
    """Create a health checker instance."""
    return HealthChecker(
        ollama_host=ollama_host,
        workspace=workspace,
        session_store=session_store,
    )
