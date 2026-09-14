"""
This module contains the SearchSchema classes.

Each SearchSchema is a stateless strategy describing *when* the search
should recurse into an improvement candidate. It holds no instance state
of its own and never touches the caller's attributes, decoupling the
search traversal strategy (DFS/BFS/A*) from runtime evaluation.
"""
from abc import ABC, abstractmethod
from typing import NamedTuple
from model.HypothesisGenerator import Hypothesis


class Candidate(NamedTuple):
    """ A pure candidate patch produced by the search traversal. """
    hypothesis: Hypothesis


class SearchSchema(ABC):
    """ A stateless strategy describing how the search space is traversed. """

    @staticmethod
    @abstractmethod
    def recurse_per_improvement() -> bool:
        """ Whether the search should recurse as soon as an improvement
        candidate is found (DFS), or accumulate improvement candidates
        and only recurse once the current hypotheses set is exhausted
        (BFS/A*).
        :rtype: bool
        """


class DFSSchema(SearchSchema):
    """ Depth-First: recurse into an improvement candidate immediately. """
    @staticmethod
    def recurse_per_improvement() -> bool:
        return True


class BFSSchema(SearchSchema):
    """ Breadth-First: exhaust all hypotheses at the current depth before
    recursing into the accumulated improvement candidates. """
    @staticmethod
    def recurse_per_improvement() -> bool:
        return False


class AStarSchema(SearchSchema):
    """ Best-First: like BFS, exhausts the current depth first. Candidate
    ordering by explanatory power is handled by HypothesisRefinement once
    the accumulated candidates are handed off for the recursive call. """
    @staticmethod
    def recurse_per_improvement() -> bool:
        return False
