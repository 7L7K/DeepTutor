"""
Prompt Service
==============

Unified prompt management for all DeepTutor modules.
"""

from .manager import PromptManager, get_prompt_manager

__all__ = [
    "PromptManager",
    "get_prompt_manager",
]
