"""SerpApi access for live place evidence."""

from happen_api.providers.serpapi.client import ProviderSnapshot, SerpApiClient, SerpApiFailure
from happen_api.providers.serpapi.normalizer import CandidateSelection, select_candidates

__all__ = [
    "CandidateSelection",
    "ProviderSnapshot",
    "SerpApiClient",
    "SerpApiFailure",
    "select_candidates",
]
