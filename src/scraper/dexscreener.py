import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DexToken:
    """Represents a token from DexScreener"""

    address: str
    name: str
    symbol: str
    chain: str
    created_timestamp: datetime
    price_usd: float
    liquidity_usd: float
    volume_24h: float
    price_change_24h: float
    txns_24h: int
    dex_url: str


class DexScreenerScraper:
    """Scraper for DexScreener new token listings"""

    BASE_URL = "https://api.dexscreener.com"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_new_solana_tokens(
        self,
        limit: int = 50,
        max_age_hours: int = 6,
    ) -> list[DexToken]:
        """
        Get newly listed Solana tokens from DexScreener.

        Args:
            limit: Maximum number of tokens to fetch
            max_age_hours: Only return tokens created within this many hours

        Returns:
            List of DexToken objects
        """
        try:
            # Get latest token profiles (new listings)
            response = await self.client.get(
                f"{self.BASE_URL}/token-profiles/latest/v1",
                params={"chainId": "solana"},
            )

            if response.status_code != 200:
                logger.warning(f"DexScreener profiles API error: {response.status_code}")
                # Try alternative endpoint
                return await self._get_from_boosted(limit, max_age_hours)

            data = response.json()
            tokens = []
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

            for item in data[:limit]:
                token = self._parse_profile(item)
                # Only include tokens with valid symbol data
                if token and token.symbol and token.symbol != "???":
                    tokens.append(token)

            # Filter by age if we have timestamp info
            if tokens and tokens[0].created_timestamp:
                tokens = [t for t in tokens if t.created_timestamp >= cutoff_time]

            # If we got too few tokens with valid data, try boosted endpoint
            if len(tokens) < 10:
                logger.info(f"Only {len(tokens)} valid tokens from profiles, trying boosted...")
                boosted = await self._get_from_boosted(limit, max_age_hours)
                # Add boosted tokens that aren't duplicates
                seen_addresses = {t.address for t in tokens}
                for bt in boosted:
                    if bt.address not in seen_addresses:
                        tokens.append(bt)
                        seen_addresses.add(bt.address)

            logger.info(f"Found {len(tokens)} new Solana tokens on DexScreener")
            return tokens

        except Exception as e:
            logger.error(f"Failed to fetch DexScreener tokens: {e}")
            return []

    async def _get_from_boosted(self, limit: int, max_age_hours: int) -> list[DexToken]:
        """Fallback: Get from boosted tokens endpoint"""
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/token-boosts/latest/v1",
            )

            if response.status_code != 200:
                logger.error(f"DexScreener boosts API error: {response.status_code}")
                return []

            data = response.json()
            tokens = []

            for item in data[:limit]:
                if item.get("chainId") == "solana":
                    token = self._parse_boost(item)
                    # Only include tokens with valid symbol data
                    if token and token.symbol and token.symbol != "???":
                        tokens.append(token)

            logger.info(f"Found {len(tokens)} boosted Solana tokens on DexScreener")
            return tokens

        except Exception as e:
            logger.error(f"DexScreener boosts failed: {e}")
            return []

    async def search_token(self, query: str) -> list[DexToken]:
        """
        Search for a token by address or name.

        Args:
            query: Token address or search term

        Returns:
            List of matching DexToken objects
        """
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/dex/search",
                params={"q": query},
            )

            if response.status_code != 200:
                return []

            data = response.json()
            tokens = []

            for pair in data.get("pairs", [])[:10]:
                token = self._parse_pair(pair)
                if token:
                    tokens.append(token)

            return tokens

        except Exception as e:
            logger.error(f"DexScreener search failed: {e}")
            return []

    async def get_token_info(self, address: str) -> Optional[DexToken]:
        """
        Get detailed info for a specific token.

        Args:
            address: Token contract address

        Returns:
            DexToken object or None
        """
        try:
            response = await self.client.get(
                f"{self.BASE_URL}/dex/tokens/{address}",
            )

            if response.status_code != 200:
                return None

            data = response.json()
            pairs = data.get("pairs", [])

            if not pairs:
                return None

            # Use the first (highest liquidity) pair
            return self._parse_pair(pairs[0])

        except Exception as e:
            logger.error(f"Failed to get token info: {e}")
            return None

    def _parse_profile(self, data: dict) -> Optional[DexToken]:
        """Parse token profile data"""
        try:
            return DexToken(
                address=data.get("tokenAddress", ""),
                name=data.get("name", "Unknown"),
                symbol=data.get("symbol", "???"),
                chain=data.get("chainId", "solana"),
                created_timestamp=datetime.now(timezone.utc),  # Profiles don't have timestamp
                price_usd=0,
                liquidity_usd=0,
                volume_24h=0,
                price_change_24h=0,
                txns_24h=0,
                dex_url=data.get("url", ""),
            )
        except Exception as e:
            logger.warning(f"Failed to parse profile: {e}")
            return None

    def _parse_boost(self, data: dict) -> Optional[DexToken]:
        """Parse boosted token data"""
        try:
            return DexToken(
                address=data.get("tokenAddress", ""),
                name=data.get("name", "Unknown"),
                symbol=data.get("symbol", "???"),
                chain=data.get("chainId", "solana"),
                created_timestamp=datetime.now(timezone.utc),
                price_usd=0,
                liquidity_usd=0,
                volume_24h=0,
                price_change_24h=0,
                txns_24h=0,
                dex_url=data.get("url", ""),
            )
        except Exception as e:
            logger.warning(f"Failed to parse boost: {e}")
            return None

    def _parse_pair(self, data: dict) -> Optional[DexToken]:
        """Parse pair data from search/token endpoints"""
        try:
            base_token = data.get("baseToken", {})

            # Parse creation timestamp
            pair_created = data.get("pairCreatedAt")
            if pair_created:
                if isinstance(pair_created, (int, float)):
                    created_time = datetime.fromtimestamp(pair_created / 1000, tz=timezone.utc)
                else:
                    created_time = datetime.now(timezone.utc)
            else:
                created_time = datetime.now(timezone.utc)

            return DexToken(
                address=base_token.get("address", ""),
                name=base_token.get("name", "Unknown"),
                symbol=base_token.get("symbol", "???"),
                chain=data.get("chainId", "solana"),
                created_timestamp=created_time,
                price_usd=float(data.get("priceUsd", 0) or 0),
                liquidity_usd=float(data.get("liquidity", {}).get("usd", 0) or 0),
                volume_24h=float(data.get("volume", {}).get("h24", 0) or 0),
                price_change_24h=float(data.get("priceChange", {}).get("h24", 0) or 0),
                txns_24h=int(data.get("txns", {}).get("h24", {}).get("buys", 0) or 0) +
                         int(data.get("txns", {}).get("h24", {}).get("sells", 0) or 0),
                dex_url=data.get("url", ""),
            )
        except Exception as e:
            logger.warning(f"Failed to parse pair: {e}")
            return None

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
