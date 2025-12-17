#!/usr/bin/env python3
"""
AI-Powered System Analyzer

Uses Mistral/Ollama for intelligent system analysis:
- Error root cause analysis
- Performance anomaly detection
- Optimization recommendations
- Daily intelligence reports

Provides actionable insights beyond simple pattern matching.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json

from .ollama_client import OllamaClient
from .performance_baselines import PerformanceBaselines


class AIAnalyzer:
    """
    AI-powered system analysis using Mistral/Ollama.

    Features:
    - Context-aware error analysis
    - Anomaly detection with explanations
    - Proactive optimization suggestions
    - Daily intelligence reports
    """

    def __init__(self, ollama_url: str = "http://localhost:11434", model: str = "mistral:latest"):
        """
        Initialize AI analyzer.

        Args:
            ollama_url: Ollama API URL
            model: Model to use (default: mistral:latest)
        """
        self.client = OllamaClient(base_url=ollama_url)
        self.model = model
        self.baselines = PerformanceBaselines()

        # System prompts for different analysis types
        self.ERROR_ANALYSIS_SYSTEM = """You are a Python system debugging expert analyzing errors in a Polymarket trading monitoring system.

Given an error message and surrounding log context, you must:
1. Identify the root cause
2. Explain why it happened
3. Suggest a specific fix (file + method + code change)
4. Rate severity: low/medium/high

Be concise and actionable. Focus on the specific error, not general advice.

Respond with JSON:
{
    "root_cause": "One-sentence root cause",
    "explanation": "2-3 sentence explanation",
    "suggested_fix": "Specific fix with file/method",
    "severity": "low/medium/high",
    "confidence": 0.0-1.0
}"""

        self.ANOMALY_ANALYSIS_SYSTEM = """You are a system performance analyst for a trading monitoring system.

Given a metric deviation from baseline, you must:
1. Explain why this might be happening (2-3 specific reasons)
2. Assess if it's concerning or normal variation
3. Suggest investigation steps or fixes

Be practical and specific to this trading system.

Respond with JSON:
{
    "explanation": "Why this deviation occurred",
    "is_concerning": true/false,
    "possible_causes": ["cause1", "cause2", "cause3"],
    "recommendation": "Specific action to take"
}"""

        self.OPTIMIZATION_SYSTEM = """You are a system optimization expert for a Python trading monitoring application.

Given 24h performance metrics, identify:
1. Bottlenecks (slow operations)
2. Resource issues (memory, API calls)
3. Inefficiencies (redundant work)

Provide 3-5 actionable optimization recommendations with priority levels.

Respond with JSON array:
[
    {
        "title": "Short title",
        "issue": "What's wrong",
        "impact": "Impact on system",
        "recommendation": "Specific fix",
        "priority": "low/medium/high"
    }
]"""

    async def analyze_error(
        self,
        error_msg: str,
        context: List[str],
        timeout: int = 30
    ) -> Optional[Dict]:
        """
        Analyze error with AI to determine root cause and fix.

        Args:
            error_msg: Error message
            context: Surrounding log lines (for context)
            timeout: AI call timeout

        Returns:
            dict: Analysis result or None on error
            {
                'root_cause': str,
                'explanation': str,
                'suggested_fix': str,
                'severity': 'low' | 'medium' | 'high',
                'confidence': float
            }
        """
        # Check if Ollama is available
        if not await self.client.is_available():
            print("[AI] Ollama not available, skipping error analysis")
            return None

        # Build prompt
        context_str = '\n'.join(context[-10:])  # Last 10 lines
        prompt = f"""
Error: {error_msg}

Context (last 10 log lines):
{context_str}

Analyze this error and provide:
- Root cause
- Explanation
- Specific fix
- Severity

Respond only with JSON.
"""

        try:
            result = await self.client.generate_json(
                prompt=prompt,
                model=self.model,
                system_prompt=self.ERROR_ANALYSIS_SYSTEM,
                timeout=timeout,
                use_cache=True
            )

            if result:
                # Validate required fields
                required = ['root_cause', 'explanation', 'suggested_fix', 'severity']
                if all(field in result for field in required):
                    # Ensure confidence is present
                    if 'confidence' not in result:
                        result['confidence'] = 0.8  # Default

                    return result

            return None

        except Exception as e:
            print(f"[AI] Error analysis failed: {e}")
            return None

    async def detect_anomaly(
        self,
        metric_name: str,
        current_value: float,
        window_hours: int = 24,
        timeout: int = 30
    ) -> Optional[Dict]:
        """
        Detect and explain performance anomaly using AI.

        Args:
            metric_name: Metric name
            current_value: Current metric value
            window_hours: Baseline time window
            timeout: AI call timeout

        Returns:
            dict: Anomaly analysis or None if not anomalous
            {
                'metric': str,
                'baseline_mean': float,
                'baseline_std': float,
                'current_value': float,
                'deviation_pct': float,
                'explanation': str,
                'is_concerning': bool,
                'possible_causes': List[str],
                'recommendation': str
            }
        """
        # Get deviation stats
        deviation = self.baselines.get_deviation(metric_name, current_value, window_hours)

        if not deviation or not deviation['is_anomaly']:
            return None

        # Check if Ollama is available
        if not await self.client.is_available():
            print("[AI] Ollama not available, returning basic anomaly info")
            return {
                'metric': metric_name,
                'baseline_mean': deviation['baseline_mean'],
                'baseline_std': deviation['baseline_std'],
                'current_value': current_value,
                'deviation_pct': deviation['deviation_pct'],
                'explanation': 'AI analysis unavailable',
                'is_concerning': True,
                'possible_causes': [],
                'recommendation': 'Check system logs for issues'
            }

        # Build prompt with context
        now = datetime.now()
        prompt = f"""
Metric: {metric_name}
Baseline: {deviation['baseline_mean']:.2f} ± {deviation['baseline_std']:.2f}
Current: {current_value:.2f}
Deviation: {deviation['deviation_pct']:.1f}% from baseline
Standard Deviations: {deviation['deviation_std']:.1f}

Time: {now.strftime('%H:%M')}
Day: {now.strftime('%A')}

Why might this metric be deviating? Should we be concerned?
What should we investigate or fix?

Respond only with JSON.
"""

        try:
            result = await self.client.generate_json(
                prompt=prompt,
                model=self.model,
                system_prompt=self.ANOMALY_ANALYSIS_SYSTEM,
                timeout=timeout,
                use_cache=True
            )

            if result:
                # Combine deviation stats with AI analysis
                return {
                    'metric': metric_name,
                    'baseline_mean': deviation['baseline_mean'],
                    'baseline_std': deviation['baseline_std'],
                    'current_value': current_value,
                    'deviation_pct': deviation['deviation_pct'],
                    'explanation': result.get('explanation', ''),
                    'is_concerning': result.get('is_concerning', True),
                    'possible_causes': result.get('possible_causes', []),
                    'recommendation': result.get('recommendation', '')
                }

            return None

        except Exception as e:
            print(f"[AI] Anomaly detection failed: {e}")
            return None

    async def suggest_optimizations(
        self,
        metrics: Dict,
        timeout: int = 45
    ) -> List[Dict]:
        """
        Analyze system metrics and suggest optimizations.

        Args:
            metrics: System metrics dict
            timeout: AI call timeout

        Returns:
            List of optimization suggestions:
            [
                {
                    'title': str,
                    'issue': str,
                    'impact': str,
                    'recommendation': str,
                    'priority': 'low' | 'medium' | 'high'
                }
            ]
        """
        # Check if Ollama is available
        if not await self.client.is_available():
            print("[AI] Ollama not available, skipping optimization analysis")
            return []

        # Build metrics summary
        metrics_summary = []
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                metrics_summary.append(f"- {key}: {value}")
            elif isinstance(value, dict):
                for subkey, subvalue in value.items():
                    metrics_summary.append(f"- {key}.{subkey}: {subvalue}")

        metrics_str = '\n'.join(metrics_summary)

        prompt = f"""
24h Performance Metrics:
{metrics_str}

Analyze these metrics and identify optimization opportunities.
Focus on:
1. Slow operations (bottlenecks)
2. Resource issues (memory, API calls)
3. Inefficiencies (redundant work)

Provide 3-5 actionable recommendations. Prioritize by impact.

Respond only with JSON array.
"""

        try:
            result = await self.client.generate_json(
                prompt=prompt,
                model=self.model,
                system_prompt=self.OPTIMIZATION_SYSTEM,
                timeout=timeout,
                use_cache=True
            )

            if result and isinstance(result, list):
                # Validate suggestions
                valid_suggestions = []
                for suggestion in result:
                    if all(k in suggestion for k in ['title', 'issue', 'recommendation', 'priority']):
                        valid_suggestions.append(suggestion)

                return valid_suggestions

            return []

        except Exception as e:
            print(f"[AI] Optimization analysis failed: {e}")
            return []

    async def generate_daily_report(
        self,
        last_24h_data: Dict,
        timeout: int = 60
    ) -> Optional[str]:
        """
        Generate intelligent daily summary report.

        Args:
            last_24h_data: 24h metrics and events
            timeout: AI call timeout

        Returns:
            str: Formatted daily report
        """
        # Check if Ollama is available
        if not await self.client.is_available():
            return "AI daily report unavailable - Ollama not reachable"

        # Build data summary
        summary_parts = []

        # Activity
        if 'activity' in last_24h_data:
            activity = last_24h_data['activity']
            summary_parts.append("Activity:")
            for key, value in activity.items():
                summary_parts.append(f"  {key}: {value}")

        # Errors
        if 'errors' in last_24h_data:
            errors = last_24h_data['errors']
            summary_parts.append(f"\nErrors: {errors.get('total', 0)}")
            if errors.get('by_type'):
                summary_parts.append("  By type:")
                for error_type, count in errors['by_type'].items():
                    summary_parts.append(f"    {error_type}: {count}")

        # Performance
        if 'performance' in last_24h_data:
            perf = last_24h_data['performance']
            summary_parts.append("\nPerformance:")
            for key, value in perf.items():
                summary_parts.append(f"  {key}: {value}")

        data_str = '\n'.join(summary_parts)

        system_prompt = """You are a system analyst generating a daily intelligence report for a trading monitoring system.

Given 24h data, create a concise summary including:
1. Activity overview (1-2 sentences)
2. Issues encountered (if any)
3. Performance trends (improving/degrading/stable)
4. Top 3 recommendations for next 24h

Keep it actionable and specific. Format as readable text (not JSON)."""

        prompt = f"""
Last 24h System Data:
{data_str}

Generate a daily intelligence report.
Include:
- Activity overview
- Issues summary
- Performance assessment
- Top 3 recommendations

Be concise and actionable.
"""

        try:
            report = await self.client.generate(
                prompt=prompt,
                model=self.model,
                system_prompt=system_prompt,
                timeout=timeout,
                use_cache=False  # Don't cache daily reports
            )

            return report

        except Exception as e:
            print(f"[AI] Daily report generation failed: {e}")
            return None

    async def is_ollama_available(self) -> bool:
        """
        Check if Ollama is available.

        Returns:
            bool: True if available
        """
        return await self.client.is_available()
