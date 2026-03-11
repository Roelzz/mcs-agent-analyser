"""Solution Checker — static analysis for Power Platform Copilot Studio solution exports.

Mirrors the intent of the Power Platform Solution Checker (pac solution check) but
focuses on Copilot Studio agent-specific rules that the generic checker does not cover.

Rules are grouped into five categories:

  - Solution   : solution.xml metadata health
  - Agent      : bot configuration.json settings
  - Topics     : topic coverage and quality
  - Knowledge  : knowledge sources and capabilities
  - Security   : security and injection risks

Returns a structured result dict suitable for storing in Reflex state.
"""

from ._helpers import CATEGORIES, _CAT_ICONS
from .checker import check_solution_zip

__all__ = ["CATEGORIES", "_CAT_ICONS", "check_solution_zip"]
