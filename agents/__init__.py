"""Skincare recommendation agents package."""

from importlib import import_module

__all__ = [
    "CompileNode",
    "Orchestrator",
    "SkinProfile",
    "StepAnalysisResult",
    "CompiledRoutine",
    "IngredientsAnalysisOutput",
    "ProductAnalysisOutput",
]


def __getattr__(name):
    """Catalog workers can import search contracts without loading the agent SDK."""
    if name not in __all__:
        raise AttributeError(name)
    module = {"CompileNode": "compile_node", "Orchestrator": "orchestrator"}.get(name, "models")
    return getattr(import_module(f"{__name__}.{module}"), name)
