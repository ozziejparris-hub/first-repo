#!/usr/bin/env python3
"""
Shared DB path resolution and write guard for scripts/simulation/ scripts.

All simulation scripts import from here. The guard lives in ONE place so
a production-path rename or policy change requires editing one file.

Usage pattern
─────────────
EVERY simulation script (reader and writer):

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from _sim_db_guard import add_sim_db_args, resolve_sim_db

    add_sim_db_args(parser)          # call before parser.parse_args()
    args = parser.parse_args()
    db_path = resolve_sim_db(args)
    db = Database(db_path)           # or sqlite3.connect(db_path)

WRITER scripts additionally, before the first write:

    from _sim_db_guard import assert_safe_to_write
    assert_safe_to_write(db_path, args.allow_production_write)
"""

import sys
from pathlib import Path

# Canonical production DB path — resolved once at import time.
_PRODUCTION_DB = (
    Path(__file__).parent.parent.parent / 'data' / 'polymarket_tracker.db'
).resolve()

# Default DB for every simulation script — clearly not production.
SIM_DB_DEFAULT = 'data/simulation_test.db'


def add_sim_db_args(parser) -> None:
    """
    Register --db-path and --allow-production-write on an ArgumentParser.
    Call before parser.parse_args().
    """
    parser.add_argument(
        '--db-path',
        default=SIM_DB_DEFAULT,
        metavar='PATH',
        help=(
            f'SQLite database to use. '
            f'Defaults to {SIM_DB_DEFAULT} (not the production database). '
            f'Writer scripts additionally require --allow-production-write '
            f'to modify data/polymarket_tracker.db.'
        ),
    )
    parser.add_argument(
        '--allow-production-write',
        action='store_true',
        help=(
            'Permit a writer simulation script to modify the production database. '
            'Has no effect on read-only scripts. '
            'Without this flag any write attempt against production exits non-zero.'
        ),
    )


def resolve_sim_db(args) -> str:
    """Return the DB path string from parsed args."""
    return args.db_path


def assert_safe_to_write(db_path: str, allow_production: bool = False) -> None:
    """
    Abort with a clear error if db_path resolves to the production database
    and allow_production is False. Call ONCE, before the first DB write.

    Read-only scripts do NOT need to call this.
    """
    resolved = Path(db_path).resolve()
    if resolved == _PRODUCTION_DB:
        if not allow_production:
            print(
                f'\nERROR: simulation script refused to write to the production database:\n'
                f'  {resolved}\n\n'
                f'Running this against production will overwrite ELO columns, reset\n'
                f'modifier values to 1.0, or inject/delete synthetic traders and trades.\n\n'
                f'To use a safe simulation database instead:\n'
                f'  --db-path data/simulation_test.db\n\n'
                f'To explicitly allow production writes (only if you are certain):\n'
                f'  --db-path data/polymarket_tracker.db --allow-production-write\n',
                file=sys.stderr,
            )
            sys.exit(1)
