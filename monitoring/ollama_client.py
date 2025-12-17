#!/usr/bin/env python3
"""
Ollama Client

Wrapper for Ollama API calls with caching, retries, and error handling.

Features:
- Async API calls
- Response caching (1h TTL)
- Retry logic with backoff
- Availability checks
- Timeout handling
"""

import asyncio
import aiohttp
import hashlib
import time
from typing import Optional, Dict
from datetime import datetime, timedelta
import json


class OllamaClient:
    """
    Ollama API client for AI model interactions.

    Features:
    - Generate text completions
    - Response caching (avoid redundant calls)
    - Connection checking
    - Timeout and retry logic
    """

    def __init__(self, base_url: str = "http://localhost:11434", cache_ttl_seconds: int = 3600):
        """
        Initialize Ollama client.

        Args:
            base_url: Ollama API base URL
            cache_ttl_seconds: Cache TTL in seconds (default: 1 hour)
        """
        self.base_url = base_url.rstrip('/')
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self.cache = {}  # {cache_key: {'response': str, 'timestamp': datetime}}
        self.last_availability_check = None
        self.is_ollama_available = None

    def _get_cache_key(self, prompt: str, model: str, system_prompt: Optional[str] = None) -> str:
        """
        Generate cache key for a prompt.

        Args:
            prompt: User prompt
            model: Model name
            system_prompt: System prompt (optional)

        Returns:
            str: Cache key (hash)
        """
        content = f"{model}:{system_prompt}:{prompt}"
        return hashlib.md5(content.encode()).hexdigest()

    def _check_cache(self, cache_key: str) -> Optional[str]:
        """
        Check if response is in cache and still valid.

        Args:
            cache_key: Cache key

        Returns:
            str: Cached response if valid, None otherwise
        """
        if cache_key not in self.cache:
            return None

        cache_entry = self.cache[cache_key]
        age = datetime.now() - cache_entry['timestamp']

        if age > self.cache_ttl:
            # Expired
            del self.cache[cache_key]
            return None

        return cache_entry['response']

    def _store_cache(self, cache_key: str, response: str):
        """
        Store response in cache.

        Args:
            cache_key: Cache key
            response: Response to cache
        """
        self.cache[cache_key] = {
            'response': response,
            'timestamp': datetime.now()
        }

        # Cleanup old entries (keep last 100)
        if len(self.cache) > 100:
            # Remove oldest entries
            sorted_keys = sorted(
                self.cache.keys(),
                key=lambda k: self.cache[k]['timestamp']
            )
            for key in sorted_keys[:-100]:
                del self.cache[key]

    async def is_available(self, timeout: int = 5) -> bool:
        """
        Check if Ollama is available.

        Args:
            timeout: Timeout in seconds

        Returns:
            bool: True if Ollama is reachable
        """
        # Cache availability check for 60 seconds
        if self.last_availability_check:
            age = (datetime.now() - self.last_availability_check).total_seconds()
            if age < 60 and self.is_ollama_available is not None:
                return self.is_ollama_available

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    available = response.status == 200
                    self.is_ollama_available = available
                    self.last_availability_check = datetime.now()
                    return available

        except (aiohttp.ClientError, asyncio.TimeoutError):
            self.is_ollama_available = False
            self.last_availability_check = datetime.now()
            return False

    async def generate(
        self,
        prompt: str,
        model: str = "mistral:latest",
        system_prompt: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        use_cache: bool = True
    ) -> Optional[str]:
        """
        Generate text completion using Ollama.

        Args:
            prompt: User prompt
            model: Model to use (default: mistral:latest)
            system_prompt: System prompt (optional)
            timeout: Timeout in seconds
            max_retries: Maximum retry attempts
            use_cache: Use cached responses if available

        Returns:
            str: Generated text, or None on error
        """
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key(prompt, model, system_prompt)
            cached = self._check_cache(cache_key)
            if cached:
                return cached

        # Prepare request
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }

        if system_prompt:
            request_data["system"] = system_prompt

        # Retry logic
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.base_url}/api/generate",
                        json=request_data,
                        timeout=aiohttp.ClientTimeout(total=timeout)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            generated_text = data.get('response', '').strip()

                            # Cache the response
                            if use_cache and generated_text:
                                cache_key = self._get_cache_key(prompt, model, system_prompt)
                                self._store_cache(cache_key, generated_text)

                            return generated_text
                        else:
                            # Non-200 status
                            error_text = await response.text()
                            print(f"[OLLAMA] API error: {response.status} - {error_text}")

                            if attempt < max_retries - 1:
                                # Exponential backoff
                                await asyncio.sleep(2 ** attempt)
                                continue
                            return None

            except asyncio.TimeoutError:
                print(f"[OLLAMA] Timeout on attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

            except aiohttp.ClientError as e:
                print(f"[OLLAMA] Connection error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

            except Exception as e:
                print(f"[OLLAMA] Unexpected error: {e}")
                return None

        return None

    async def generate_json(
        self,
        prompt: str,
        model: str = "mistral:latest",
        system_prompt: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        use_cache: bool = True
    ) -> Optional[Dict]:
        """
        Generate JSON response using Ollama.

        Same as generate() but parses response as JSON.

        Args:
            prompt: User prompt
            model: Model to use
            system_prompt: System prompt (optional)
            timeout: Timeout in seconds
            max_retries: Maximum retry attempts
            use_cache: Use cached responses

        Returns:
            dict: Parsed JSON response, or None on error
        """
        # Modify system prompt to request JSON
        json_system_prompt = (system_prompt or "") + "\n\nYou must respond with valid JSON only. No additional text."

        response = await self.generate(
            prompt=prompt,
            model=model,
            system_prompt=json_system_prompt,
            timeout=timeout,
            max_retries=max_retries,
            use_cache=use_cache
        )

        if not response:
            return None

        # Try to parse JSON
        try:
            # Extract JSON from response (sometimes AI adds text around it)
            # Look for {...} pattern
            start = response.find('{')
            end = response.rfind('}')

            if start != -1 and end != -1:
                json_str = response[start:end + 1]
                return json.loads(json_str)
            else:
                # Try parsing entire response
                return json.loads(response)

        except json.JSONDecodeError as e:
            print(f"[OLLAMA] JSON parse error: {e}")
            print(f"[OLLAMA] Response was: {response[:200]}...")
            return None

    def clear_cache(self):
        """Clear the response cache."""
        self.cache = {}

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics.

        Returns:
            dict: Cache stats (size, hit rate, etc.)
        """
        return {
            'size': len(self.cache),
            'oldest_entry': min(
                (entry['timestamp'] for entry in self.cache.values()),
                default=None
            ),
            'newest_entry': max(
                (entry['timestamp'] for entry in self.cache.values()),
                default=None
            )
        }
