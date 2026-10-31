"""Agent registry: the graph refers to agents by name."""

from orchestrator.agents.analysis import (
    DesignAgent,
    ImpactAnalysisAgent,
    PlanningAgent,
    RequirementsAgent,
)
from orchestrator.agents.base import Agent, AgentContext
from orchestrator.agents.build import DocsAgent, ImplementationAgent, TemplateDocsAgent, TestAgent
from orchestrator.agents.governance import ReleaseAgent, ReviewAgent

REGISTRY: dict[str, type[Agent]] = {
    cls.name: cls
    for cls in (
        RequirementsAgent,
        PlanningAgent,
        ImpactAnalysisAgent,
        DesignAgent,
        ImplementationAgent,
        TestAgent,
        DocsAgent,
        TemplateDocsAgent,
        ReviewAgent,
        ReleaseAgent,
    )
}

__all__ = ["REGISTRY", "Agent", "AgentContext"]
