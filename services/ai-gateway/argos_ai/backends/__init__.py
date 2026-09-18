"""Inference backends: one contract, three implementations (ARG-051, ADR-0009).

The model is configuration, not code. Nothing above this package names a model or a server: it
asks for a completion and gets one. In the appliance that is vLLM, in development llama.cpp, and
in the tests a deterministic file — which is what makes the CI reproducible without a GPU.
"""

from .base import Backend, Completion

__all__ = ["Backend", "Completion"]
