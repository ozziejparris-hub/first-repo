"""
Analysis tools for Polymarket trader tracking.

Available modules:
- correlation_matrix: Trader correlation analysis and cluster detection
- copy_trade_detector: Leader-follower relationship detection via time-lag analysis
"""

from .correlation_matrix import TraderCorrelationMatrix
from .copy_trade_detector import CopyTradeDetector

__all__ = ['TraderCorrelationMatrix', 'CopyTradeDetector']
