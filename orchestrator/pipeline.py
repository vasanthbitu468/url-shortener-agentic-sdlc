"""The default SDLC pipeline: stages, dependencies, gates, approvals and recovery rules.

    requirements -> planning -> impact_analysis* -> design -> implementation
    implementation -+-> tests -+-> review -> release
                    +-> docs  -+
    * optional: planning skips it for greenfield work

Human approval checkpoints (high-impact): requirements (only when ambiguities exist),
design (when the API contract or schema changes), release (always).
Recovery: tests or review failing after retries -> roll back and rework implementation;
docs failing after retries -> fallback template docs.
"""

from __future__ import annotations

from orchestrator import gates
from orchestrator.graph import Graph, Stage
from orchestrator.models import Impact, RetryPolicy


def default_pipeline(retry: RetryPolicy | None = None) -> Graph:
    r = retry or RetryPolicy()
    quick = RetryPolicy(
        max_attempts=r.max_attempts, backoff_seconds=r.backoff_seconds, timeout_seconds=120
    )
    return Graph(
        [
            Stage(
                name="requirements",
                agent="requirements",
                outputs=("spec",),
                exit_gate=gates.spec_is_complete,
                approval=gates.approve_if_ambiguous,
                retry=quick,
                impact=Impact.MEDIUM,
                description="Normalise the request into a spec; surface ambiguities",
            ),
            Stage(
                name="planning",
                agent="planning",
                depends_on=("requirements",),
                inputs=("spec",),
                outputs=("plan",),
                entry_gate=gates.requires_artifacts("spec"),
                exit_gate=gates.plan_is_valid,
                retry=quick,
                description="Decompose into a task DAG; choose optional stages",
            ),
            Stage(
                name="impact_analysis",
                agent="impact_analysis",
                depends_on=("planning",),
                inputs=("spec", "plan"),
                outputs=("impact",),
                exit_gate=gates.impact_is_grounded,
                optional=True,
                retry=quick,
                description="Map the change onto existing modules, APIs and data flows",
            ),
            Stage(
                name="design",
                agent="design",
                depends_on=("impact_analysis",),
                inputs=("spec", "plan", "impact"),
                outputs=("design",),
                entry_gate=gates.requires_artifacts("spec", "plan"),
                exit_gate=gates.design_is_complete,
                approval=gates.approve_if_contract_or_schema_change,
                retry=quick,
                impact=Impact.HIGH,
                description="API/schema design and ADR",
            ),
            Stage(
                name="implementation",
                agent="implementation",
                depends_on=("design",),
                inputs=("spec", "design"),
                outputs=("implementation",),
                writes=("service",),
                entry_gate=gates.requires_artifacts("design"),
                exit_gate=gates.implementation_applied,
                retry=r,
                impact=Impact.HIGH,
                description="Change the code in the sandbox workspace",
            ),
            Stage(
                name="tests",
                agent="tests",
                depends_on=("implementation",),
                inputs=("spec", "implementation"),
                outputs=("test_report",),
                writes=("tests",),
                exit_gate=gates.tests_pass,
                retry=r,
                rework_target="implementation",
                description="Write tests and run the full suite",
            ),
            Stage(
                name="docs",
                agent="docs",
                depends_on=("implementation",),
                inputs=("spec", "design"),
                outputs=("docs",),
                writes=("docs",),
                exit_gate=gates.docs_written,
                retry=r,
                fallback_agent="docs_template",
                description="Developer and API documentation",
            ),
            Stage(
                name="review",
                agent="review",
                depends_on=("tests", "docs"),
                inputs=("design", "implementation", "test_report", "docs"),
                outputs=("policy_report",),
                exit_gate=gates.policies_pass,
                retry=RetryPolicy(max_attempts=1),  # deterministic: retrying cannot help
                rework_target="implementation",
                impact=Impact.HIGH,
                description="Security, compliance and change-control policies; lint",
            ),
            Stage(
                name="release",
                agent="release",
                depends_on=("review",),
                inputs=("policy_report", "test_report"),
                outputs=("release",),
                exit_gate=gates.release_ready,
                approval=gates.always,
                retry=RetryPolicy(max_attempts=1),
                impact=Impact.HIGH,
                description="Patch, PR description, release-readiness sign-off",
            ),
        ]
    )
