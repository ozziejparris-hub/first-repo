#!/usr/bin/env python3
"""
run_tests.py — test suite runner for tests/test_*.py

Discovers all tests/test_*.py files, runs each as a subprocess,
collects results, and reports an aggregate summary.

Usage:
    python3 run_tests.py                                # quiet: one line per file
    python3 run_tests.py --verbose                      # full output for all files
    python3 run_tests.py --skip=test_foo.py             # exclude a file from this run
    python3 run_tests.py --skip=test_foo.py,test_bar.py # exclude multiple files

Exit code: 0 only if ALL test files pass; non-zero if ANY fail.

Note on test_behavioral_integration.py: this test calls UnifiedELOSystem which
triggers a full analyze_all_traders() run when its in-memory cache is cold.
Each subprocess starts with a cold cache, so this test always hangs in automation.
Exclude it with --skip=test_behavioral_integration.py for CI/pre-commit use.
"""

import re
import subprocess
import sys
from glob import glob
from pathlib import Path

TIMEOUT_SECONDS = 300
TEST_GLOB = "tests/test_*.py"
SEP = "=" * 70
RULE = "─" * 70


def parse_counts(output: str):
    """
    Extract (tests_run, passed, failed) from a test file's summary output.
    Both TestResults variants print lines that match these patterns:
      'Tests run    : 30'  /  'Tests run: 8'
      'Passed       : 30'  /  'Passed: 8 (100.0%)'
      'Failed       : 0'   /  'Failed: 0'
    Returns None if any field is missing.
    """
    run_m = re.search(r'Tests run\s*:\s*(\d+)', output)
    pass_m = re.search(r'Passed\s*:\s*(\d+)', output)
    fail_m = re.search(r'Failed\s*:\s*(\d+)', output)
    if run_m and pass_m and fail_m:
        return int(run_m.group(1)), int(pass_m.group(1)), int(fail_m.group(1))
    return None


def run_file(test_path: Path):
    """
    Run a single test file as a subprocess.
    Returns (passed: bool, output: str, counts: tuple|None).
    counts is (tests_run, passed, failed) parsed from output, or None.
    """
    try:
        result = subprocess.run(
            [sys.executable, str(test_path)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        output = result.stdout
        if result.stderr:
            output += result.stderr
        passed = result.returncode == 0
    except subprocess.TimeoutExpired:
        output = f"[TIMEOUT] {test_path.name} did not finish within {TIMEOUT_SECONDS}s.\n"
        passed = False
    except Exception as exc:
        output = f"[ERROR] Could not launch {test_path.name}: {exc}\n"
        passed = False

    counts = parse_counts(output)
    return passed, output, counts


def parse_args():
    verbose = False
    skip = set()
    for arg in sys.argv[1:]:
        if arg in ("--verbose", "-v"):
            verbose = True
        elif arg.startswith("--skip="):
            names = arg[len("--skip="):].split(",")
            skip.update(n.strip() for n in names if n.strip())
        elif arg not in ("--verbose", "-v"):
            print(f"Unknown argument: {arg}", file=sys.stderr)
            print("Usage: python3 run_tests.py [--verbose] [--skip=file1.py,file2.py]", file=sys.stderr)
            sys.exit(2)
    return verbose, skip


def main():
    verbose, skip = parse_args()

    all_files = sorted(Path(p) for p in glob(TEST_GLOB))
    test_files = [f for f in all_files if f.name not in skip]
    skipped = [f for f in all_files if f.name in skip]

    if not all_files:
        print(f"No test files found matching: {TEST_GLOB}")
        sys.exit(1)

    print()
    print(SEP)
    print("  TEST SUITE RUNNER")
    n_info = f"{len(test_files)} file(s) found  ({TEST_GLOB})"
    if skipped:
        n_info += f"  [skipping {len(skipped)}: {', '.join(f.name for f in skipped)}]"
    print(f"  {n_info}")
    print(SEP)
    print()

    file_results = []
    agg_run = agg_pass = agg_fail = 0
    counts_partial = False

    for test_path in test_files:
        passed, output, counts = run_file(test_path)

        if verbose:
            print(RULE)
            print(f"  {test_path.name}")
            print(RULE)
            print(output, end="" if output.endswith("\n") else "\n")

        if counts:
            run, p, f = counts
            agg_run += run
            agg_pass += p
            agg_fail += f
            label = f"  ({run} tests, {p} passed)"
        else:
            counts_partial = True
            label = ""

        status = "PASS" if passed else "FAIL"
        print(f"  {status}  {test_path.name}{label}")

        # In quiet mode, dump the full output on failure so the error is visible.
        if not passed and not verbose:
            print()
            print(output, end="" if output.endswith("\n") else "\n")

        file_results.append((test_path.name, passed))

    files_passed = sum(1 for _, p in file_results if p)
    files_failed = len(file_results) - files_passed
    all_passed = files_failed == 0

    print()
    print(SEP)
    print("  SUMMARY")
    print(SEP)
    print(f"  Files  : {len(file_results)} run, {files_passed} passed, {files_failed} failed")
    if agg_run > 0:
        note = " (partial — one or more files had unparseable counts)" if counts_partial else ""
        print(f"  Tests  : {agg_run} run, {agg_pass} passed, {agg_fail} failed{note}")
    print()
    if all_passed:
        print("  RESULT: ALL TESTS PASSED")
    else:
        print("  RESULT: FAILURES DETECTED")
        for name, ok in file_results:
            if not ok:
                print(f"    - {name}")
    print(SEP)
    print()

    # Critical: non-zero exit if any file failed. This is what gates pre-commit / CI.
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
