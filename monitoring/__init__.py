"""
Polymarket monitoring package.

Core monitoring components for tracking geopolitical prediction markets.
"""

from .database import Database
from .polymarket_client import PolymarketClient
from .trader_analyzer import TraderAnalyzer

# Import components with external dependencies conditionally
__all__ = [
    'Database',
    'PolymarketClient',
    'TraderAnalyzer',
]

try:
    from .telegram_bot import TelegramNotifier
    __all__.append('TelegramNotifier')
except ImportError:
    pass

try:
    from .monitor import PolymarketMonitor
    __all__.append('PolymarketMonitor')
except ImportError:
    pass
