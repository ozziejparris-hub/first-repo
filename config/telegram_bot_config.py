"""Telegram ELO Bot Configuration."""

# ============================================================
# SCHEDULING
# ============================================================

# Daily leaderboard time (24-hour format)
DAILY_LEADERBOARD_HOUR = 9  # 9 AM
DAILY_LEADERBOARD_MINUTE = 0

# ============================================================
# ELO THRESHOLDS
# ============================================================

# Minimum ELO to be considered "elite"
ELITE_ELO_THRESHOLD = 1800

# Top N traders to monitor for alerts
TOP_N_FOR_ALERTS = 10

# ============================================================
# BETTING INTELLIGENCE THRESHOLDS
# ============================================================

# Minimum win streak to trigger alert
MIN_WIN_STREAK = 3

# Large position multiplier (e.g., 3.0 = 3x normal bet size)
LARGE_POSITION_MULTIPLIER = 3.0

# Minimum elite traders needed for momentum alert
MARKET_MOMENTUM_MIN_TRADERS = 2

# Contrarian thresholds
CONTRARIAN_YES_THRESHOLD = 0.3  # Alert if betting YES when market < 30%
CONTRARIAN_NO_THRESHOLD = 0.7   # Alert if betting NO when market > 70%

# ============================================================
# FEATURE TOGGLES
# ============================================================

# Enable/disable specific features
ENABLE_DAILY_LEADERBOARD = True
ENABLE_ELITE_TRADER_ALERTS = True
ENABLE_MOMENTUM_ALERTS = True
ENABLE_CONTRARIAN_ALERTS = True
ENABLE_LARGE_POSITION_ALERTS = True
ENABLE_WIN_STREAK_ALERTS = True

# ============================================================
# MESSAGE FORMATTING
# ============================================================

# Maximum market title length in alerts
MAX_MARKET_TITLE_LENGTH = 80

# Number of traders to show in momentum alerts
MOMENTUM_TRADERS_DISPLAY_LIMIT = 5
