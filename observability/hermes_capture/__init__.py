"""Optional Hermes plugin: metadata-only LLM/tool capture to local JSONL.

Not installed or discovered from this location. Disabled unless
TFG_OBSERVABILITY_CAPTURE=1 and an absolute TFG_OBSERVABILITY_DIR are set.
"""
from .capture import register

__all__ = ["register"]
