from autodrafter.search.base import Suggestion, SearchResult, Searcher
from autodrafter.search.greedy import GreedySearcher
from autodrafter.search.alphabeta import AlphaBetaSearcher
from autodrafter.search.mcts import MCTSSearcher

ALGORITHMS = {
    "greedy": GreedySearcher,
    "alphabeta": AlphaBetaSearcher,
    "mcts": MCTSSearcher,
}

__all__ = ["Suggestion", "SearchResult", "Searcher", "ALGORITHMS",
           "GreedySearcher", "AlphaBetaSearcher", "MCTSSearcher"]
