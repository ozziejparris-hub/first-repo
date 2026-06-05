"""
Comprehensive investigation of Polymarket API resolution data.

This script analyzes how Polymarket exposes market resolution information
and documents the correct way to detect and extract resolution data.
"""

import sys
import os
import json
import requests
from datetime import datetime
from typing import Dict, List, Any

# Add parent directory to path to import monitoring modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from monitoring.polymarket_client import PolymarketClient
from monitoring.database import Database


class ResolutionInvestigator:
    """Investigates Polymarket market resolution data structures."""

    def __init__(self):
        self.client = PolymarketClient()
        self.db = Database()
        self.session = requests.Session()
        self.gamma_api_base = "https://gamma-api.polymarket.com"

        # Findings storage
        self.findings = {
            'market_categories': {},
            'resolution_fields': [],
            'id_formats': {},
            'outcome_structures': [],
            'edge_cases': [],
            'sample_markets': []
        }

    def print_section(self, title: str):
        """Print a formatted section header."""
        print("\n" + "=" * 80)
        print(title.center(80))
        print("=" * 80 + "\n")

    def step1_fetch_diverse_markets(self) -> Dict[str, List[Dict]]:
        """
        Step 1: Fetch diverse sample of markets and categorize them.

        Returns:
            Dict with keys: 'active', 'closed', 'archived'
        """
        self.print_section("STEP 1: FETCHING DIVERSE MARKET SAMPLE")

        print("Fetching 500 markets from Gamma API...")

        markets = []
        offset = 0
        batch_size = 100

        while len(markets) < 500:
            try:
                response = self.session.get(
                    f"{self.gamma_api_base}/markets",
                    params={"limit": batch_size, "offset": offset},
                    timeout=30
                )

                if response.status_code != 200:
                    print(f"API request failed: {response.status_code}")
                    break

                data = response.json()
                if not data:
                    break

                markets.extend(data)
                offset += batch_size
                print(f"  Fetched {len(markets)} markets...", end='\r')

            except Exception as e:
                print(f"\nError fetching markets: {e}")
                break

        print(f"\n  Total markets fetched: {len(markets)}")

        # Categorize markets
        categorized = {
            'active': [],
            'closed': [],
            'archived': []
        }

        for market in markets:
            if market.get('archived'):
                categorized['archived'].append(market)
            elif market.get('closed'):
                categorized['closed'].append(market)
            else:
                categorized['active'].append(market)

        print(f"\nMarket Categories:")
        print(f"  Active:   {len(categorized['active'])}")
        print(f"  Closed:   {len(categorized['closed'])}")
        print(f"  Archived: {len(categorized['archived'])}")

        self.findings['market_categories'] = {
            'active': len(categorized['active']),
            'closed': len(categorized['closed']),
            'archived': len(categorized['archived'])
        }

        return categorized

    def step2_identify_resolved_markets(self, categorized: Dict[str, List[Dict]]) -> List[Dict]:
        """
        Step 2: Identify resolved markets and print examples.

        Args:
            categorized: Markets categorized by status

        Returns:
            List of resolved markets
        """
        self.print_section("STEP 2: IDENTIFYING RESOLVED MARKETS")

        # Combine closed and archived markets
        potential_resolved = categorized['closed'] + categorized['archived']

        print(f"Examining {len(potential_resolved)} closed/archived markets...")

        # Check for resolution indicators
        resolved_markets = []

        for market in potential_resolved:
            # Check multiple resolution indicators
            uma_status = market.get('umaResolutionStatus', '')
            outcomes = market.get('outcomes', '[]')
            prices = market.get('outcomePrices', '[]')

            try:
                # Parse prices
                if isinstance(prices, str):
                    prices = json.loads(prices)

                # Check if any outcome has winning price (>= 0.99)
                has_winner = any(float(p) >= 0.99 for p in prices if p)

                if has_winner or uma_status == 'resolved':
                    resolved_markets.append(market)

            except:
                continue

        print(f"Found {len(resolved_markets)} resolved markets\n")

        # Print first 10 examples
        print("First 10 resolved market examples:")
        for i, market in enumerate(resolved_markets[:10], 1):
            title = market.get('question', market.get('title', 'Unknown'))[:70]
            closed = market.get('closed', False)
            archived = market.get('archived', False)
            print(f"  {i:2d}. {title}")
            print(f"      Closed: {closed} | Archived: {archived}")

        return resolved_markets

    def step3_detailed_examination(self, resolved_markets: List[Dict]):
        """
        Step 3: Examine detailed structure of resolved markets.

        Args:
            resolved_markets: List of resolved markets
        """
        self.print_section("STEP 3: DETAILED STRUCTURE EXAMINATION")

        # Pick 5 diverse resolved markets
        sample_markets = resolved_markets[:5]

        for i, market in enumerate(sample_markets, 1):
            print(f"\n{'-' * 80}")
            print(f"MARKET {i}/5: {market.get('question', 'Unknown')[:70]}")
            print(f"{'-' * 80}\n")

            # Print complete JSON structure
            print("COMPLETE JSON STRUCTURE:")
            print(json.dumps(market, indent=2, ensure_ascii=False)[:2000])  # Limit output
            print("...\n")

            # Extract resolution-related fields
            print("RESOLUTION-RELATED FIELDS:")

            resolution_fields = {}
            for key, value in market.items():
                key_lower = key.lower()
                if any(keyword in key_lower for keyword in [
                    'outcome', 'result', 'winner', 'winning',
                    'payout', 'settled', 'resolved', 'resolution',
                    'closed', 'archived', 'active', 'ended', 'uma'
                ]):
                    resolution_fields[key] = value
                    print(f"  {key}: {value}")

            self.findings['resolution_fields'].append(resolution_fields)

            # Save sample market
            self.findings['sample_markets'].append(market)

    def step4_market_id_investigation(self, sample_markets: List[Dict]):
        """
        Step 4: Investigate different ID formats and their usage.

        Args:
            sample_markets: Sample markets to examine
        """
        self.print_section("STEP 4: MARKET ID INVESTIGATION")

        print("Examining ID fields across sample markets:\n")

        id_formats = {
            'id': [],
            'conditionId': [],
            'questionID': [],
            'other_ids': []
        }

        for i, market in enumerate(sample_markets[:5], 1):
            print(f"Market {i}: {market.get('question', 'Unknown')[:50]}")

            # Check all possible ID fields
            market_id = market.get('id')
            condition_id = market.get('conditionId')
            question_id = market.get('questionID')

            print(f"  id:          {market_id}")
            print(f"  conditionId: {condition_id}")
            print(f"  questionID:  {question_id}")

            if market_id:
                id_formats['id'].append(market_id)
            if condition_id:
                id_formats['conditionId'].append(condition_id)
            if question_id:
                id_formats['questionID'].append(question_id)

            # Look for other ID-like fields
            for key, value in market.items():
                if 'id' in key.lower() and key not in ['id', 'conditionId', 'questionID']:
                    print(f"  {key}: {value}")
                    id_formats['other_ids'].append({key: value})

            # Test API lookup with different IDs
            print(f"\n  Testing API lookups:")

            if market_id:
                test_url = f"{self.gamma_api_base}/markets/{market_id}"
                try:
                    response = self.session.get(test_url, timeout=5)
                    print(f"    Using id ({market_id}): {response.status_code}")
                except Exception as e:
                    print(f"    Using id: FAILED - {e}")

            if condition_id:
                test_url = f"{self.gamma_api_base}/markets/{condition_id}"
                try:
                    response = self.session.get(test_url, timeout=5)
                    print(f"    Using conditionId: {response.status_code}")
                except Exception as e:
                    print(f"    Using conditionId: FAILED")

            print()

        self.findings['id_formats'] = id_formats

        # Summary
        print("\nID FORMAT SUMMARY:")
        print(f"  Markets with 'id': {len(id_formats['id'])}")
        print(f"  Markets with 'conditionId': {len(id_formats['conditionId'])}")
        print(f"  Markets with 'questionID': {len(id_formats['questionID'])}")
        print(f"\n  RECOMMENDATION: Use 'id' for API lookups, store both 'id' and 'conditionId'")

    def step5_outcome_structure_analysis(self, resolved_markets: List[Dict]):
        """
        Step 5: Analyze outcome structure and winner detection.

        Args:
            resolved_markets: List of resolved markets
        """
        self.print_section("STEP 5: OUTCOME STRUCTURE ANALYSIS")

        print("Analyzing outcome structures for resolved markets:\n")

        for i, market in enumerate(resolved_markets[:5], 1):
            print(f"{'-' * 80}")
            print(f"Market {i}: {market.get('question', 'Unknown')[:60]}")
            print(f"{'-' * 80}")

            # Get outcomes and prices
            outcomes_raw = market.get('outcomes', '[]')
            prices_raw = market.get('outcomePrices', '[]')

            print(f"\nRaw outcomes: {outcomes_raw}")
            print(f"Raw prices:   {prices_raw}")

            try:
                # Parse JSON strings if necessary
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

                print(f"\nParsed outcomes: {outcomes}")
                print(f"Parsed prices:   {prices}")

                # Identify winner
                winner = None
                winner_idx = None

                for idx, price in enumerate(prices):
                    price_float = float(price)
                    is_winner = price_float >= 0.99

                    print(f"\n  Outcome {idx}: '{outcomes[idx]}'")
                    print(f"    Price: {price_float:.4f}")
                    print(f"    Winner: {'YES [WINNER]' if is_winner else 'NO'}")

                    if is_winner:
                        winner = outcomes[idx]
                        winner_idx = idx

                if winner:
                    print(f"\n  -> WINNER: '{winner}' (index {winner_idx})")
                else:
                    print(f"\n  -> NO CLEAR WINNER DETECTED")
                    self.findings['edge_cases'].append({
                        'market': market.get('question'),
                        'issue': 'No clear winner (all prices < 0.99)',
                        'prices': prices
                    })

                # Check for other resolution fields
                if market.get('umaResolutionStatus'):
                    print(f"\n  UMA Resolution Status: {market.get('umaResolutionStatus')}")

                if market.get('resolvedBy'):
                    print(f"  Resolved By: {market.get('resolvedBy')}")

                self.findings['outcome_structures'].append({
                    'question': market.get('question'),
                    'outcomes': outcomes,
                    'prices': prices,
                    'winner': winner
                })

            except Exception as e:
                print(f"\n  ERROR parsing outcomes: {e}")
                self.findings['edge_cases'].append({
                    'market': market.get('question'),
                    'issue': f'Parse error: {e}',
                    'outcomes_raw': outcomes_raw,
                    'prices_raw': prices_raw
                })

            print()

    def step6_save_findings(self):
        """
        Step 6: Save findings to documentation files.
        """
        self.print_section("STEP 6: SAVING FINDINGS")

        # Create docs directory
        os.makedirs('docs', exist_ok=True)

        # Save sample resolved markets
        sample_file = 'docs/resolved_market_samples.json'
        with open(sample_file, 'w', encoding='utf-8') as f:
            json.dump(self.findings['sample_markets'][:5], f, indent=2, ensure_ascii=False)
        print(f"Saved sample markets to: {sample_file}")

        # Create API resolution structure documentation
        doc_file = 'docs/API_RESOLUTION_STRUCTURE.md'
        with open(doc_file, 'w', encoding='utf-8') as f:
            f.write(self._generate_documentation())
        print(f"Saved documentation to: {doc_file}")

        # Save complete findings
        findings_file = 'docs/investigation_findings.json'
        with open(findings_file, 'w', encoding='utf-8') as f:
            # Remove full market objects to keep file size reasonable
            summary_findings = {
                'market_categories': self.findings['market_categories'],
                'id_formats': self.findings['id_formats'],
                'outcome_structures': self.findings['outcome_structures'],
                'edge_cases': self.findings['edge_cases'],
                'investigation_date': datetime.now().isoformat()
            }
            json.dump(summary_findings, f, indent=2, ensure_ascii=False)
        print(f"Saved investigation findings to: {findings_file}")

    def _generate_documentation(self) -> str:
        """Generate comprehensive documentation from findings."""
        doc = f"""# Polymarket API Resolution Structure

**Investigation Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary

This document details how to detect market resolution and extract winning outcomes
from the Polymarket Gamma API.

## Market Categories

Based on analysis of {self.findings['market_categories'].get('active', 0) + self.findings['market_categories'].get('closed', 0) + self.findings['market_categories'].get('archived', 0)} markets:

- **Active Markets:** {self.findings['market_categories'].get('active', 0)}
- **Closed Markets:** {self.findings['market_categories'].get('closed', 0)}
- **Archived Markets:** {self.findings['market_categories'].get('archived', 0)}

## Resolution Detection Logic

### Primary Method: Outcome Prices

The most reliable way to detect a resolved market:

```python
def is_market_resolved(market: dict) -> bool:
    \"\"\"Check if market is resolved by examining outcome prices.\"\"\"
    try:
        prices_raw = market.get('outcomePrices', '[]')
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

        # Market is resolved if any outcome has price >= 0.99
        return any(float(p) >= 0.99 for p in prices if p)
    except:
        return False
```

### Secondary Indicators

- `closed: true` - Market is closed for trading
- `archived: true` - Market is archived
- `umaResolutionStatus: "resolved"` - UMA oracle has resolved (unreliable)

**Note:** Not all closed markets are resolved, and not all resolved markets have
`umaResolutionStatus == "resolved"`. Always use outcome prices as primary indicator.

## Field Mapping

| API Field | Database Field | Type | Description |
|-----------|---------------|------|-------------|
| `id` | `api_id` | Integer | Numeric ID for API lookups |
| `conditionId` | `market_id`, `condition_id` | String (hex) | Blockchain condition ID |
| `question` | `title` | String | Market question |
| `outcomes` | - | JSON string | Array of outcome names |
| `outcomePrices` | - | JSON string | Array of outcome prices |
| `closed` | - | Boolean | Market closed for trading |
| `archived` | `archived` | Boolean | Market archived |
| `category` | `category` | String | Market category |
| `endDate` | `end_date` | Timestamp | Market end date |

## Extracting Winning Outcome

```python
def extract_winner(market: dict) -> str:
    \"\"\"Extract winning outcome from resolved market.\"\"\"
    try:
        outcomes_raw = market.get('outcomes', '[]')
        prices_raw = market.get('outcomePrices', '[]')

        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

        # Find outcome with price >= 0.99
        for idx, price in enumerate(prices):
            if float(price) >= 0.99:
                return outcomes[idx]

        return None
    except Exception as e:
        return None
```

## Market ID Strategy

### Recommended Approach

1. **Primary Key:** Use `conditionId` (hex string) as `market_id`
   - Unique identifier
   - Used in blockchain transactions
   - Required for matching trades

2. **API Lookup:** Use `id` (numeric) as `api_id`
   - Required for Gamma API endpoints
   - Example: `GET /markets/{{id}}`

3. **Database Schema:**
```sql
CREATE TABLE markets (
    market_id TEXT PRIMARY KEY,      -- conditionId
    api_id TEXT,                      -- numeric id
    condition_id TEXT,                -- duplicate of market_id for clarity
    ...
);
```

## Edge Cases Identified

"""

        # Add edge cases
        if self.findings['edge_cases']:
            doc += "### Edge Cases Found:\n\n"
            for i, case in enumerate(self.findings['edge_cases'], 1):
                doc += f"{i}. **{case.get('issue', 'Unknown')}**\n"
                doc += f"   - Market: {case.get('market', 'N/A')[:60]}\n"
                if 'prices' in case:
                    doc += f"   - Prices: {case['prices']}\n"
                doc += "\n"
        else:
            doc += "No edge cases identified in sample.\n\n"

        doc += """
## Example Code

### Complete Resolution Checker

```python
import json
import requests

def check_market_resolution(market_id: str) -> dict:
    \"\"\"
    Check if market is resolved and extract winner.

    Args:
        market_id: Numeric market ID (api_id)

    Returns:
        {
            'resolved': bool,
            'winner': str or None,
            'closed': bool
        }
    \"\"\"
    response = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}")
    if response.status_code != 200:
        return {'resolved': False, 'winner': None, 'closed': False}

    market = response.json()

    # Parse outcomes
    try:
        outcomes_raw = market.get('outcomes', '[]')
        prices_raw = market.get('outcomePrices', '[]')

        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

        # Find winner
        winner = None
        for idx, price in enumerate(prices):
            if float(price) >= 0.99:
                winner = outcomes[idx]
                break

        return {
            'resolved': winner is not None,
            'winner': winner,
            'closed': market.get('closed', False)
        }
    except:
        return {'resolved': False, 'winner': None, 'closed': market.get('closed', False)}
```

## Outcome Structure Examples

"""

        # Add outcome examples
        if self.findings['outcome_structures']:
            for i, outcome in enumerate(self.findings['outcome_structures'][:3], 1):
                doc += f"### Example {i}\n\n"
                doc += f"**Question:** {outcome.get('question', 'N/A')[:70]}\n\n"
                doc += f"**Outcomes:** `{outcome.get('outcomes')}`\n\n"
                doc += f"**Prices:** `{outcome.get('prices')}`\n\n"
                doc += f"**Winner:** `{outcome.get('winner')}`\n\n"

        doc += """
## Recommendations

1. **Always use outcome prices** as the primary resolution indicator
2. **Store both IDs:** `conditionId` for database key, `id` for API lookups
3. **Handle edge cases:** Markets with no clear winner (all prices < 0.99)
4. **Use threshold 0.99** instead of exact 1.0 for floating-point tolerance
5. **Parse JSON strings:** Both `outcomes` and `outcomePrices` are JSON strings

## Testing

Test the resolution detection with these commands:

```bash
# Diagnose resolution matching
python monitoring/diagnose_resolution_matching.py

# Run fast batch resolution check (test mode)
python monitoring/fast_resolution_check.py --test --limit 100

# Update database with resolutions
python monitoring/fast_resolution_check.py --limit 1000
```

---

*Generated by: scripts/investigate_resolutions.py*
"""

        return doc

    def run_investigation(self):
        """Run complete investigation workflow."""
        print("\n" + "=" * 80)
        print("POLYMARKET RESOLUTION DATA INVESTIGATION".center(80))
        print("=" * 80)

        try:
            # Step 1: Fetch diverse markets
            categorized = self.step1_fetch_diverse_markets()

            # Step 2: Identify resolved markets
            resolved_markets = self.step2_identify_resolved_markets(categorized)

            if not resolved_markets:
                print("\n[WARNING] No resolved markets found!")
                return

            # Step 3: Detailed examination
            self.step3_detailed_examination(resolved_markets)

            # Step 4: ID investigation
            self.step4_market_id_investigation(resolved_markets)

            # Step 5: Outcome analysis
            self.step5_outcome_structure_analysis(resolved_markets)

            # Step 6: Save findings
            self.step6_save_findings()

            # Final summary
            self.print_section("INVESTIGATION COMPLETE")
            print("Key Findings:")
            print(f"  - Examined {len(resolved_markets)} resolved markets")
            print(f"  - Identified {len(self.findings['edge_cases'])} edge cases")
            print(f"  - Analyzed {len(self.findings['outcome_structures'])} outcome structures")
            print("\nDocumentation saved to:")
            print("  - docs/API_RESOLUTION_STRUCTURE.md")
            print("  - docs/resolved_market_samples.json")
            print("  - docs/investigation_findings.json")
            print()

        except Exception as e:
            print(f"\n[ERROR] Investigation failed: {e}")
            import traceback
            traceback.print_exc()


def main():
    """Main entry point."""
    investigator = ResolutionInvestigator()
    investigator.run_investigation()


if __name__ == "__main__":
    main()
