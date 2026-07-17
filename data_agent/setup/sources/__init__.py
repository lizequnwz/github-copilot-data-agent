"""Source-specific semantic extraction interfaces."""

from data_agent.setup.sources.generic import extract_generic_ir
from data_agent.setup.sources.powerbi import extract_powerbi, extract_powerbi_ir
from data_agent.setup.sources.tableau import extract_tableau, extract_tableau_ir

__all__ = [
    "extract_generic_ir",
    "extract_powerbi",
    "extract_powerbi_ir",
    "extract_tableau",
    "extract_tableau_ir",
]
