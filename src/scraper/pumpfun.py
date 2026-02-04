import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class PumpFunToken:
    """Represents a token from pump.fun"""

    address: str
    name: str
    symbol: str
    description: str
    image_uri: Optional[str]
    creator: str
    created_timestamp: datetime
    market_cap: float
    reply_count: int
    website: Optional[str]
    twitter: Optional[str]
    telegram: Optional[str]


class PumpFunScraper:
    """Scraper for pump.fun new token launches"""

    BASE_URL = "https://frontend-api.pump.fun"

    # Browser-like headers to avoid Cloudflare blocks
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "https://pump.fun",
        "Referer": "https://pump.fun/",
    }

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0, headers=self.HEADERS)

    async def get_new_tokens(
        self,
        limit: int = 50,
        max_age_hours: int = 6,
    ) -> list[PumpFunToken]:
        """
        Get newly launched tokens from pump.fun.

        Args:
            limit: Maximum number of tokens to fetch
            max_age_hours: Only return tokens created within this many hours

        Returns:
            List of PumpFunToken objects
        """
        # Try multiple endpoints
        endpoints = [
            f"{self.BASE_URL}/coins",
            "https://client-api-2-74b1891ee9f9.herokuapp.com/coins",
        ]

        for endpoint in endpoints:
            try:
                response = await self.client.get(
                    endpoint,
                    params={
                        "offset": 0,
                        "limit": limit,
                        "sort": "created_timestamp",
                        "order": "DESC",
                        "includeNsfw": "false",
                    },
                )

                if response.status_code != 200:
                    logger.warning(f"Pump.fun endpoint {endpoint} returned: {response.status_code}")
                    continue

                data = response.json()
                tokens = []
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

                for item in data:
                    token = self._parse_token(item)
                    if token and token.created_timestamp >= cutoff_time:
                        tokens.append(token)

                if tokens:
                    logger.info(f"Found {len(tokens)} new pump.fun tokens (last {max_age_hours}h)")
                    return tokens

            except Exception as e:
                logger.warning(f"Endpoint {endpoint} failed: {e}")
                continue

        logger.error("All pump.fun endpoints failed")
        return []

    async def get_king_of_hill(self) -> list[PumpFunToken]:
        """
        Get tokens currently on the "King of the Hill" (trending/graduated).

        Returns:
            List of PumpFunToken objects
        """
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/coins/king-of-the-hill",
                params={"includeNsfw": "false"},
            )

            if response.status_code != 200:
                logger.error(f"Pump.fun API error: {response.status_code}")
                return []

            data = response.json()
            tokens = [self._parse_token(item) for item in data if item]
            tokens = [t for t in tokens if t is not None]

            logger.info(f"Found {len(tokens)} King of Hill tokens")
            return tokens

        except Exception as e:
            logger.error(f"Failed to fetch King of Hill: {e}")
            return []

    async def search_token(self, query: str) -> list[PumpFunToken]:
        """
        Search for tokens by name/symbol.

        Args:
            query: Search query

        Returns:
            List of matching PumpFunToken objects
        """
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/coins",
                params={
                    "searchTerm": query,
                    "limit": 20,
                    "sort": "market_cap",
                    "order": "DESC",
                },
            )

            if response.status_code != 200:
                return []

            data = response.json()
            tokens = [self._parse_token(item) for item in data if item]
            return [t for t in tokens if t is not None]

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def _parse_token(self, data: dict) -> Optional[PumpFunToken]:
        """Parse token data from API response"""
        try:
            # Parse timestamp
            created_ts = data.get("created_timestamp")
            if isinstance(created_ts, (int, float)):
                # Timestamp in milliseconds
                if created_ts > 1e12:
                    created_ts = created_ts / 1000
                created_time = datetime.fromtimestamp(created_ts, tz=timezone.utc)
            else:
                created_time = datetime.now(timezone.utc)

            return PumpFunToken(
                address=data.get("mint", ""),
                name=data.get("name", "Unknown"),
                symbol=data.get("symbol", "???"),
                description=data.get("description", ""),
                image_uri=data.get("image_uri"),
                creator=data.get("creator", ""),
                created_timestamp=created_time,
                market_cap=float(data.get("usd_market_cap", 0) or 0),
                reply_count=int(data.get("reply_count", 0) or 0),
                website=data.get("website"),
                twitter=data.get("twitter"),
                telegram=data.get("telegram"),
            )
        except Exception as e:
            logger.warning(f"Failed to parse token: {e}")
            return None

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
