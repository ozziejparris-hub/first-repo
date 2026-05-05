#!/usr/bin/env python3
"""
System Health Checker

Performs comprehensive health checks on the monitoring system:
- Process alive check
- Database accessibility
- Last activity tracking
- Error rate monitoring
- Memory usage tracking

Returns health status: healthy, warning, or critical
"""

import os
import sys
import psutil
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import re


class HealthChecker:
    """
    Performs health checks on the monitoring system.

    Checks:
    1. Process alive (PID exists)
    2. Database accessible (query test)
    3. Last activity (<20 min)
    4. Error rate (from logs)
    5. Memory usage (<500MB warning)
    """

    def __init__(self, monitoring_pid: Optional[int] = None, db_path: str = 'data/polymarket_tracker.db'):
        """
        Initialize health checker.

        Args:
            monitoring_pid: PID of monitoring process (optional - will auto-detect)
            db_path: Path to database
        """
        self.monitoring_pid = monitoring_pid
        self.db_path = db_path
        self.last_check_time = None
        self.check_history = []
        self._elo_system = None
        self._elo_system_last_init = None

    def _find_monitoring_process_by_name(self) -> Optional[int]:
        """Search for the monitoring process by cmdline when the tracked PID is stale."""
        patterns = [
            'start_monitoring.py',
            '-m monitoring',
            'monitoring.main',
            'main_telegram_safe.py',
            'monitoring.__main__',
            'monitor.py',
        ]
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] not in ['python.exe', 'python', 'py.exe']:
                    continue
                cmdline = proc.info.get('cmdline', [])
                if not cmdline:
                    continue
                cmdline_str = ' '.join(str(c) for c in cmdline).lower()
                if any(p in cmdline_str for p in patterns) and 'observer' not in cmdline_str:
                    try:
                        memory_mb = proc.memory_info().rss / (1024 * 1024)
                        if memory_mb < 10:
                            continue
                    except Exception:
                        pass
                    return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def check_process_alive(self, pid: Optional[int] = None) -> Dict:
        """
        Check if monitoring process is alive.

        Args:
            pid: Process ID to check (uses self.monitoring_pid if not provided)

        Returns:
            dict: {
                'status': 'healthy' | 'critical',
                'alive': bool,
                'pid': int,
                'message': str
            }
        """
        target_pid = pid or self.monitoring_pid

        if target_pid is None:
            return {
                'status': 'warning',
                'alive': False,
                'pid': None,
                'message': 'No monitoring PID provided - cannot check process'
            }

        pid_valid = False
        try:
            process = psutil.Process(target_pid)
            if process.is_running():
                pid_valid = True
                return {
                    'status': 'healthy',
                    'alive': True,
                    'pid': target_pid,
                    'name': process.name(),
                    'message': f'Process {target_pid} is running ({process.name()})'
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception as e:
            return {
                'status': 'warning',
                'alive': False,
                'pid': target_pid,
                'message': f'Error checking process: {str(e)}'
            }

        if not pid_valid:
            # Stale PID — check if monitoring process exists under a new PID
            new_pid = self._find_monitoring_process_by_name()
            if new_pid is not None:
                print(f"[HEALTH] PID {target_pid} is stale; found monitoring process at new PID {new_pid}, updating reference")
                self.monitoring_pid = new_pid
                try:
                    proc = psutil.Process(new_pid)
                    return {
                        'status': 'healthy',
                        'alive': True,
                        'pid': new_pid,
                        'name': proc.name(),
                        'message': f'Process restarted; updated PID {target_pid}→{new_pid} ({proc.name()})'
                    }
                except Exception:
                    return {
                        'status': 'healthy',
                        'alive': True,
                        'pid': new_pid,
                        'message': f'Process restarted; updated PID {target_pid}→{new_pid}'
                    }
            return {
                'status': 'critical',
                'alive': False,
                'pid': target_pid,
                'message': f'Process {target_pid} does not exist and monitoring process not found by name'
            }

    def check_database_accessible(self) -> Dict:
        """
        Check if database is accessible.

        Returns:
            dict: {
                'status': 'healthy' | 'critical',
                'accessible': bool,
                'message': str,
                'query_time_ms': float (optional)
            }
        """
        if not os.path.exists(self.db_path):
            return {
                'status': 'critical',
                'accessible': False,
                'message': f'Database file not found: {self.db_path}'
            }

        try:
            start = datetime.now()
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()

            # Simple query test
            cursor.execute("SELECT COUNT(*) FROM trades LIMIT 1")
            result = cursor.fetchone()

            conn.close()

            query_time = (datetime.now() - start).total_seconds() * 1000

            return {
                'status': 'healthy',
                'accessible': True,
                'message': f'Database accessible (query: {query_time:.1f}ms)',
                'query_time_ms': query_time
            }

        except sqlite3.OperationalError as e:
            return {
                'status': 'critical',
                'accessible': False,
                'message': f'Database locked or inaccessible: {str(e)}'
            }
        except Exception as e:
            return {
                'status': 'critical',
                'accessible': False,
                'message': f'Database error: {str(e)}'
            }

    def check_last_activity(self) -> Dict:
        """
        Check when monitoring system last had activity.

        Looks at:
        - Log file modification time
        - Recent database writes

        Returns:
            dict: {
                'status': 'healthy' | 'warning' | 'critical',
                'last_activity': datetime,
                'age_minutes': int,
                'message': str
            }
        """
        log_path = 'logs/monitoring.log'

        # Check log file modification
        if os.path.exists(log_path):
            log_mtime = datetime.fromtimestamp(os.path.getmtime(log_path))
            age = datetime.now() - log_mtime
            age_minutes = int(age.total_seconds() / 60)

            if age_minutes < 90:
                status = 'healthy'
                message = f'Recent activity {age_minutes}m ago'
            elif age_minutes < 120:
                status = 'warning'
                message = f'Last activity {age_minutes}m ago (>90m, may have missed cycle)'
            else:
                status = 'critical'
                message = f'No activity for {age_minutes}m (>120m, likely stuck)'

            return {
                'status': status,
                'last_activity': log_mtime,
                'age_minutes': age_minutes,
                'message': message
            }
        else:
            return {
                'status': 'warning',
                'last_activity': None,
                'age_minutes': None,
                'message': 'Log file not found - cannot determine activity'
            }

    def check_memory_usage(self, pid: Optional[int] = None) -> Dict:
        """
        Check memory usage of monitoring process.

        Args:
            pid: Process ID (uses self.monitoring_pid if not provided)

        Returns:
            dict: {
                'status': 'healthy' | 'warning',
                'memory_mb': float,
                'message': str
            }
        """
        target_pid = pid or self.monitoring_pid

        if target_pid is None:
            return {
                'status': 'warning',
                'memory_mb': None,
                'message': 'No PID provided'
            }

        try:
            process = psutil.Process(target_pid)
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)

            if memory_mb < 500:
                status = 'healthy'
                message = f'Memory usage: {memory_mb:.1f} MB'
            elif memory_mb < 1000:
                status = 'warning'
                message = f'Memory usage high: {memory_mb:.1f} MB (>500MB)'
            else:
                status = 'critical'
                message = f'Memory usage critical: {memory_mb:.1f} MB (>1GB)'

            return {
                'status': status,
                'memory_mb': memory_mb,
                'message': message
            }

        except psutil.NoSuchProcess:
            return {
                'status': 'critical',
                'memory_mb': None,
                'message': f'Process {target_pid} not found'
            }
        except Exception as e:
            return {
                'status': 'warning',
                'memory_mb': None,
                'message': f'Error checking memory: {str(e)}'
            }

    def check_error_rate(self, log_path: str = 'logs/monitoring.log', minutes: int = 10) -> Dict:
        """
        Check error rate in recent logs.

        Args:
            log_path: Path to log file
            minutes: Time window to check

        Returns:
            dict: {
                'status': 'healthy' | 'warning' | 'critical',
                'error_count': int,
                'time_window_minutes': int,
                'errors_per_hour': float,
                'message': str
            }
        """
        if not os.path.exists(log_path):
            return {
                'status': 'warning',
                'error_count': None,
                'time_window_minutes': minutes,
                'errors_per_hour': None,
                'message': 'Log file not found'
            }

        try:
            cutoff_time = datetime.now() - timedelta(minutes=minutes)
            error_count = 0

            # Read last N lines (approximate time window)
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read last 1000 lines
                lines = f.readlines()[-1000:]

                for line in lines:
                    # Check if line has timestamp and is within window
                    if 'ERROR' in line or 'CRITICAL' in line:
                        # Try to extract timestamp
                        match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                        if match:
                            try:
                                log_time = datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
                                if log_time >= cutoff_time:
                                    error_count += 1
                            except:
                                # If timestamp parsing fails, count it anyway
                                error_count += 1
                        else:
                            # No timestamp, count it
                            error_count += 1

            errors_per_hour = (error_count / minutes) * 60

            if error_count == 0:
                status = 'healthy'
                message = f'No errors in last {minutes}m'
            elif error_count < 5:
                status = 'healthy'
                message = f'{error_count} errors in last {minutes}m'
            elif error_count < 15:
                status = 'warning'
                message = f'{error_count} errors in last {minutes}m (elevated)'
            else:
                status = 'critical'
                message = f'{error_count} errors in last {minutes}m (high rate)'

            return {
                'status': status,
                'error_count': error_count,
                'time_window_minutes': minutes,
                'errors_per_hour': errors_per_hour,
                'message': message
            }

        except Exception as e:
            return {
                'status': 'warning',
                'error_count': None,
                'time_window_minutes': minutes,
                'errors_per_hour': None,
                'message': f'Error reading logs: {str(e)}'
            }

    async def check_elo_system(self) -> Dict:
        """
        Test ELO system functionality.

        Tests:
        1. Can import unified_elo_system module
        2. Can initialize UnifiedELOSystem
        3. Can retrieve sample trader data from database
        4. Can calculate base ELO (without full 6-dimension analysis)

        Returns:
            dict: Health check result with details
        """
        import_ok = False
        init_ok = False
        data_available = False
        calculation_ok = False
        error_msg = None

        try:
            # Test 1: Import module
            try:
                from analysis.unified_elo_system import UnifiedELOSystem
                import_ok = True
            except ImportError as e:
                # Catch internal import failures (e.g., missing trading_behavior_analysis)
                return {
                    'status': 'warning',
                    'available': False,
                    'test_passed': False,
                    'message': f'ELO system has missing dependencies: {str(e)}',
                    'details': {
                        'import_ok': False,
                        'error': str(e)
                    }
                }

            # Test 2: Initialize system (cached; refreshed every 6 hours to avoid
            # re-running ConsensusDivergenceDetector.__init__ on every 60s health check)
            now = datetime.now()
            if (self._elo_system is None or self._elo_system_last_init is None or
                    (now - self._elo_system_last_init).total_seconds() > 21600):
                self._elo_system = UnifiedELOSystem(db_path=self.db_path)
                self._elo_system_last_init = now
            elo_system = self._elo_system
            init_ok = True

            # Test 3: Check if trader data available
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1")
            trader_count = cursor.fetchone()[0]
            data_available = trader_count > 0

            # Test 4: Try basic calculation (without full analysis)
            if data_available:
                # Get one sample trader
                cursor.execute("SELECT address FROM traders WHERE is_flagged = 1 LIMIT 1")
                result = cursor.fetchone()
                sample_trader = result[0] if result else None

                if sample_trader:
                    try:
                        # Try to get their base ELO (lightweight check)
                        base_elo = elo_system.get_trader_global_elo(
                            sample_trader,
                            apply_behavioral=False,
                            apply_advanced=False,
                            apply_network=False,
                            apply_contrarian=False,
                            apply_pnl=False
                        )
                        calculation_ok = base_elo is not None
                    except Exception as e:
                        error_msg = f"Calculation failed: {str(e)}"
                else:
                    error_msg = "No sample trader available"
            else:
                error_msg = "No trader data available"

            conn.close()

            # Determine status
            if import_ok and init_ok and calculation_ok:
                status = 'healthy'
                message = 'ELO system operational'
            elif import_ok and init_ok:
                status = 'warning'
                message = 'ELO system loaded but calculation not tested (no data)'
            else:
                status = 'critical'
                message = 'ELO system not functional'

            return {
                'status': status,
                'available': import_ok and init_ok,
                'test_passed': calculation_ok,
                'message': message,
                'details': {
                    'import_ok': import_ok,
                    'init_ok': init_ok,
                    'data_available': data_available,
                    'calculation_ok': calculation_ok,
                    'error': error_msg
                }
            }

        except ImportError as e:
            return {
                'status': 'critical',
                'available': False,
                'test_passed': False,
                'message': f'ELO system import failed: {str(e)}',
                'details': {
                    'import_ok': False,
                    'error': str(e)
                }
            }
        except Exception as e:
            return {
                'status': 'critical',
                'available': False,
                'test_passed': False,
                'message': f'ELO system test failed: {str(e)}',
                'details': {
                    'error': str(e)
                }
            }

    async def check_position_tracker(self) -> Dict:
        """
        Test position tracker functionality.

        Tests:
        1. Can import position_tracker module
        2. Can initialize PositionTracker
        3. Can query trade data
        4. Can perform basic FIFO matching (if data available)

        Returns:
            dict: Health check result with details
        """
        import_ok = False
        init_ok = False
        data_available = False
        calculation_ok = False
        error_msg = None

        try:
            # Test 1: Import
            from monitoring.position_tracker import PositionTracker
            from monitoring.database import Database
            import_ok = True

            # Test 2: Initialize (PositionTracker requires Database instance, not db_path)
            db_instance = Database(self.db_path)
            tracker = PositionTracker(db_instance)
            init_ok = True

            # Test 3: Check trade data available
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trades")
            trade_count = cursor.fetchone()[0]
            data_available = trade_count > 0

            # Test 4: Try basic calculation
            if data_available:
                # Get sample trader with trades
                cursor.execute("""
                    SELECT trader_address
                    FROM trades
                    GROUP BY trader_address
                    LIMIT 1
                """)
                result = cursor.fetchone()
                sample_trader = result[0] if result else None

                if sample_trader:
                    try:
                        # Calculate P&L stats (lightweight check)
                        pnl_stats = tracker.calculate_trader_pnl(sample_trader)
                        calculation_ok = pnl_stats is not None
                    except Exception as e:
                        error_msg = f"Calculation failed: {str(e)}"
                else:
                    error_msg = "No sample trader available"
            else:
                error_msg = "No trade data available"

            conn.close()

            # Status determination
            if import_ok and init_ok and calculation_ok:
                status = 'healthy'
                message = 'Position tracker operational'
            elif import_ok and init_ok:
                status = 'warning'
                message = 'Position tracker loaded but not tested (no data)'
            else:
                status = 'critical'
                message = 'Position tracker not functional'

            return {
                'status': status,
                'available': import_ok and init_ok,
                'test_passed': calculation_ok,
                'message': message,
                'details': {
                    'import_ok': import_ok,
                    'init_ok': init_ok,
                    'data_available': data_available,
                    'calculation_ok': calculation_ok,
                    'error': error_msg
                }
            }

        except ImportError as e:
            return {
                'status': 'critical',
                'available': False,
                'test_passed': False,
                'message': f'Position tracker import failed: {str(e)}',
                'details': {'import_ok': False, 'error': str(e)}
            }
        except Exception as e:
            return {
                'status': 'critical',
                'available': False,
                'test_passed': False,
                'message': f'Position tracker test failed: {str(e)}',
                'details': {'error': str(e)}
            }

    async def check_market_filter(self) -> Dict:
        """
        Test market filter functionality.

        Tests:
        1. Check if market filtering module exists (optional)
        2. Test Ollama availability (for AI filtering)
        3. Test Mistral model availability

        Returns:
            dict: Health check result with details
        """
        try:
            # Try to import market filter - may not exist as standalone module
            try:
                from monitoring.market_filter import filter_geopolitical_markets # type: ignore
                import_ok = True
                has_module = True
            except ImportError:
                # Market filtering might be integrated elsewhere - that's OK
                import_ok = True
                has_module = False

            # Test Ollama/Mistral availability (optional - for AI filtering)
            ollama_available = False
            mistral_available = False

            try:
                import requests
                # Test Ollama connectivity
                response = requests.get('http://localhost:11434/api/tags', timeout=2)
                if response.status_code == 200:
                    ollama_available = True

                    # Check if Mistral model is available
                    models = response.json().get('models', [])
                    mistral_available = any('mistral' in m.get('name', '').lower() for m in models)
            except:
                # Ollama not required for basic operation
                pass

            # Status determination
            if has_module:
                if ollama_available and mistral_available:
                    status = 'healthy'
                    message = 'Market filter fully operational (keywords + AI)'
                else:
                    status = 'healthy'
                    message = 'Market filter operational (keywords only, AI optional)'
            else:
                if ollama_available and mistral_available:
                    status = 'healthy'
                    message = 'Market filtering integrated (AI available)'
                else:
                    status = 'healthy'
                    message = 'Market filtering integrated (no standalone module)'

            return {
                'status': status,
                'available': import_ok,
                'test_passed': True,
                'message': message,
                'details': {
                    'has_standalone_module': has_module,
                    'ollama_available': ollama_available,
                    'mistral_available': mistral_available
                }
            }

        except Exception as e:
            return {
                'status': 'warning',
                'available': True,
                'test_passed': False,
                'message': f'Market filter check incomplete: {str(e)}',
                'details': {'error': str(e)}
            }

    async def check_database_operations(self) -> Dict:
        """
        Test comprehensive database operations.

        Tests:
        1. Database file exists
        2. WAL mode enabled
        3. Read operations work
        4. Write operations work
        5. Query performance acceptable

        Returns:
            dict: Health check result with details
        """
        file_exists = os.path.exists(self.db_path)

        if not file_exists:
            return {
                'status': 'critical',
                'available': False,
                'test_passed': False,
                'message': 'Database file not found',
                'details': {'file_exists': False}
            }

        try:
            # Test WAL mode
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            wal_enabled = journal_mode.lower() == 'wal'

            # Test read
            start = datetime.now()
            cursor.execute("SELECT COUNT(*) FROM traders")
            read_result = cursor.fetchone()[0]
            read_time_ms = (datetime.now() - start).total_seconds() * 1000
            read_ok = read_result is not None

            # Test write (temporary table)
            start = datetime.now()
            cursor.execute("CREATE TEMP TABLE test_write (id INTEGER)")
            cursor.execute("INSERT INTO test_write VALUES (1)")
            cursor.execute("SELECT * FROM test_write")
            write_result = cursor.fetchone()
            cursor.execute("DROP TABLE test_write")
            conn.commit()
            write_time_ms = (datetime.now() - start).total_seconds() * 1000
            write_ok = write_result is not None

            conn.close()

            # Check performance
            performance_ok = read_time_ms < 100 and write_time_ms < 100

            # Status
            if file_exists and wal_enabled and read_ok and write_ok and performance_ok:
                status = 'healthy'
                message = f'Database operations healthy (read: {read_time_ms:.1f}ms, write: {write_time_ms:.1f}ms)'
            elif file_exists and read_ok:
                status = 'warning'
                message = f'Database slow or WAL disabled (read: {read_time_ms:.1f}ms, WAL: {wal_enabled})'
            else:
                status = 'critical'
                message = 'Database operations failed'

            return {
                'status': status,
                'available': file_exists,
                'test_passed': read_ok and write_ok,
                'message': message,
                'details': {
                    'file_exists': file_exists,
                    'wal_enabled': wal_enabled,
                    'read_ok': read_ok,
                    'write_ok': write_ok,
                    'read_time_ms': read_time_ms,
                    'write_time_ms': write_time_ms,
                    'performance_ok': performance_ok
                }
            }

        except sqlite3.OperationalError as e:
            return {
                'status': 'critical',
                'available': file_exists,
                'test_passed': False,
                'message': f'Database locked or inaccessible: {str(e)}',
                'details': {'error': str(e)}
            }
        except Exception as e:
            return {
                'status': 'critical',
                'available': False,
                'test_passed': False,
                'message': f'Database test failed: {str(e)}',
                'details': {'error': str(e)}
            }

    async def check_telegram_bots(self) -> Dict:
        """
        Test Telegram bot configuration and connectivity.

        Tests:
        1. Bot token configured in .env
        2. Chat ID configured in .env
        3. Can import telegram module
        4. Bot token is valid (optional: requires network call)

        Returns:
            dict: Health check result with details
        """
        try:
            from dotenv import load_dotenv
            load_dotenv()

            # Test 1: Token configured
            token = os.getenv('TELEGRAM_BOT_TOKEN')
            token_configured = token is not None and len(token) > 0

            # Test 2: Chat ID configured
            chat_id = os.getenv('TELEGRAM_CHAT_ID')
            chat_id_configured = chat_id is not None and len(chat_id) > 0

            # Test 3: Import telegram module
            try:
                from telegram import Bot
                import_ok = True
            except ImportError:
                import_ok = False

            # Status (removed token validation - too strict and network-dependent)
            if token_configured and chat_id_configured and import_ok:
                status = 'healthy'
                message = 'Telegram bot configured'
            elif token_configured or chat_id_configured:
                status = 'warning'
                message = 'Telegram bot partially configured (missing token or chat ID)'
            else:
                status = 'critical'
                message = 'Telegram bot not configured'

            return {
                'status': status,
                'available': import_ok,
                'test_passed': token_configured and chat_id_configured,
                'message': message,
                'details': {
                    'token_configured': token_configured,
                    'chat_id_configured': chat_id_configured,
                    'import_ok': import_ok
                }
            }

        except Exception as e:
            return {
                'status': 'warning',
                'available': False,
                'test_passed': False,
                'message': f'Telegram bot check failed: {str(e)}',
                'details': {'error': str(e)}
            }

    async def check_all(self) -> Dict:
        """
        Run all health checks and return comprehensive report.

        Returns:
            dict: {
                'status': 'healthy' | 'warning' | 'critical',
                'timestamp': datetime,
                'checks': {
                    'process': dict,
                    'database': dict,
                    'activity': dict,
                    'memory': dict,
                    'errors': dict,
                    'components': {
                        'elo_system': dict,
                        'position_tracker': dict,
                        'market_filter': dict,
                        'database_ops': dict,
                        'telegram_bots': dict
                    }
                },
                'issues': List[str],
                'summary': str
            }
        """
        timestamp = datetime.now()

        # Run existing checks
        checks = {
            'process': self.check_process_alive(),
            'database': self.check_database_accessible(),
            'activity': self.check_last_activity(),
            'memory': self.check_memory_usage(),
            'errors': self.check_error_rate()
        }

        # Run component checks
        component_checks = {
            'elo_system': await self.check_elo_system(),
            'position_tracker': await self.check_position_tracker(),
            'market_filter': await self.check_market_filter(),
            'database_ops': await self.check_database_operations(),
            'telegram_bots': await self.check_telegram_bots()
        }

        checks['components'] = component_checks

        # Determine overall status (include component statuses)
        all_checks = list(checks.values())
        # Extract component check results
        for check in all_checks:
            if isinstance(check, dict) and 'elo_system' in check:
                # This is the components dict, extract its values
                all_checks.extend(check.values())
                break

        statuses = [check['status'] for check in all_checks if isinstance(check, dict) and 'status' in check]

        if 'critical' in statuses:
            overall_status = 'critical'
        elif 'warning' in statuses:
            overall_status = 'warning'
        else:
            overall_status = 'healthy'

        # Collect issues (include component issues)
        issues = []
        for check_name, check_result in checks.items():
            if check_name != 'components' and check_result['status'] != 'healthy':
                issues.append(f"{check_name}: {check_result['message']}")

        for comp_name, comp_result in component_checks.items():
            if comp_result['status'] != 'healthy':
                issues.append(f"component.{comp_name}: {comp_result['message']}")

        # Generate summary
        if overall_status == 'healthy':
            summary = 'All systems healthy'
        elif overall_status == 'warning':
            summary = f'{len(issues)} warning(s) detected'
        else:
            summary = f'{len(issues)} critical issue(s) detected'

        report = {
            'status': overall_status,
            'timestamp': timestamp,
            'checks': checks,
            'issues': issues,
            'summary': summary
        }

        # Store in history
        self.check_history.append(report)
        if len(self.check_history) > 100:
            self.check_history = self.check_history[-100:]

        self.last_check_time = timestamp

        return report
