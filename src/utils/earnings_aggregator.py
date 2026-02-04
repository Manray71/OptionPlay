# OptionPlay - Multi-Source Earnings Aggregator
# ===============================================
# Robust earnings date detection with majority voting across multiple sources.

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from collections import Counter

logger = logging.getLogger(__name__)


class EarningsSource(Enum):
    """Available earnings data sources."""
    MARKETDATA = "marketdata"
    YAHOO_DIRECT = "yahoo_direct"
    YFINANCE = "yfinance"
    
    @property
    def confidence(self) -> int:
        """
        Confidence weight for this source (higher = more reliable).
        
        Based on historical reliability:
        - Marketdata.app: Professional API, generally accurate
        - Yahoo Direct: Official API, good for upcoming earnings
        - yfinance: Library wrapper, sometimes stale data
        """
        weights = {
            EarningsSource.MARKETDATA: 3,
            EarningsSource.YAHOO_DIRECT: 2,
            EarningsSource.YFINANCE: 1,
        }
        return weights.get(self, 1)


@dataclass
class EarningsResult:
    """Single earnings result from one source."""
    source: EarningsSource
    earnings_date: Optional[str]  # ISO format: YYYY-MM-DD
    days_to_earnings: Optional[int]
    success: bool = True
    error: Optional[str] = None
    
    @property
    def confidence(self) -> int:
        """Get source confidence weight."""
        return self.source.confidence if self.success and self.earnings_date else 0


@dataclass
class AggregatedEarnings:
    """
    Aggregated earnings result with consensus information.
    
    Attributes:
        symbol: Ticker symbol
        consensus_date: Most agreed-upon date (majority voting)
        days_to_earnings: Days until consensus date
        confidence: Overall confidence score (0-100)
        sources_agree: Number of sources agreeing on consensus
        total_sources: Total number of sources queried
        all_results: Individual results from each source
        discrepancy_warning: True if sources disagree significantly
    """
    symbol: str
    consensus_date: Optional[str] = None
    days_to_earnings: Optional[int] = None
    confidence: int = 0
    sources_agree: int = 0
    total_sources: int = 0
    all_results: List[EarningsResult] = field(default_factory=list)
    discrepancy_warning: bool = False
    discrepancy_details: Optional[str] = None
    
    @property
    def is_reliable(self) -> bool:
        """Check if result is reliable enough for trading decisions."""
        # At least 2 sources agree OR single source with high confidence
        return (
            (self.sources_agree >= 2) or 
            (self.confidence >= 60 and self.sources_agree == 1)
        )
    
    @property
    def source_summary(self) -> str:
        """Get summary of which sources were used."""
        successful = [r.source.value for r in self.all_results if r.success and r.earnings_date]
        return ", ".join(successful) if successful else "none"


class EarningsAggregator:
    """
    Aggregates earnings dates from multiple sources using majority voting.
    
    Strategy:
    1. Query all available sources in parallel
    2. Group results by date (with 1-day tolerance for timing differences)
    3. Apply confidence-weighted voting
    4. Return consensus with reliability metrics
    
    Usage:
        aggregator = EarningsAggregator()
        result = aggregator.aggregate([
            EarningsResult(EarningsSource.MARKETDATA, "2025-04-15", 80),
            EarningsResult(EarningsSource.YAHOO_DIRECT, "2025-04-15", 80),
            EarningsResult(EarningsSource.YFINANCE, "2025-04-16", 81),
        ])
        
        print(result.consensus_date)  # "2025-04-15"
        print(result.confidence)       # 83 (weighted)
        print(result.is_reliable)      # True
    """
    
    # Allow 1-day tolerance for date matching (AM vs PM earnings)
    DATE_TOLERANCE_DAYS = 1
    
    def __init__(self):
        pass
    
    def aggregate(
        self, 
        symbol: str,
        results: List[EarningsResult]
    ) -> AggregatedEarnings:
        """
        Aggregate multiple earnings results into consensus.
        
        Args:
            symbol: Ticker symbol
            results: List of EarningsResult from different sources
            
        Returns:
            AggregatedEarnings with consensus and confidence metrics
        """
        aggregated = AggregatedEarnings(
            symbol=symbol,
            all_results=results,
            total_sources=len(results)
        )
        
        # Filter successful results with valid dates
        valid_results = [
            r for r in results 
            if r.success and r.earnings_date
        ]
        
        if not valid_results:
            logger.debug(f"No valid earnings data for {symbol}")
            return aggregated
        
        # Group by date (with tolerance)
        date_groups = self._group_by_date(valid_results)
        
        if not date_groups:
            return aggregated
        
        # Find consensus using weighted voting
        consensus_date, agreeing_results = self._find_consensus(date_groups)
        
        if consensus_date:
            aggregated.consensus_date = consensus_date
            aggregated.sources_agree = len(agreeing_results)
            
            # Calculate days to earnings
            try:
                earnings_dt = datetime.strptime(consensus_date, "%Y-%m-%d").date()
                aggregated.days_to_earnings = (earnings_dt - date.today()).days
            except ValueError:
                logger.debug(f"Could not parse consensus earnings date: {consensus_date!r}")
            
            # Calculate confidence score (0-100)
            aggregated.confidence = self._calculate_confidence(
                agreeing_results, 
                valid_results
            )
            
            # Check for significant discrepancies
            if len(date_groups) > 1:
                aggregated.discrepancy_warning = True
                aggregated.discrepancy_details = self._format_discrepancy(date_groups)
                logger.warning(
                    f"Earnings date discrepancy for {symbol}: {aggregated.discrepancy_details}"
                )
        
        return aggregated
    
    def _group_by_date(
        self, 
        results: List[EarningsResult]
    ) -> Dict[str, List[EarningsResult]]:
        """
        Group results by date with tolerance.
        
        Dates within DATE_TOLERANCE_DAYS are considered the same
        (handles AM/PM earnings timing differences).
        """
        groups: Dict[str, List[EarningsResult]] = {}
        
        for result in results:
            if not result.earnings_date:
                continue
            
            try:
                result_date = datetime.strptime(result.earnings_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            
            # Find existing group within tolerance
            matched_group = None
            for group_date_str in groups.keys():
                group_date = datetime.strptime(group_date_str, "%Y-%m-%d").date()
                diff = abs((result_date - group_date).days)
                if diff <= self.DATE_TOLERANCE_DAYS:
                    matched_group = group_date_str
                    break
            
            if matched_group:
                groups[matched_group].append(result)
            else:
                groups[result.earnings_date] = [result]
        
        return groups
    
    def _find_consensus(
        self, 
        date_groups: Dict[str, List[EarningsResult]]
    ) -> tuple[Optional[str], List[EarningsResult]]:
        """
        Find consensus date using confidence-weighted voting.
        
        Returns:
            Tuple of (consensus_date, list of agreeing results)
        """
        if not date_groups:
            return None, []
        
        # Calculate weighted score for each date group
        scored_groups = []
        for date_str, results in date_groups.items():
            # Sum of confidence weights
            weight = sum(r.confidence for r in results)
            # Bonus for multiple sources agreeing
            agreement_bonus = len(results) * 2
            total_score = weight + agreement_bonus
            scored_groups.append((date_str, results, total_score))
        
        # Sort by score (highest first)
        scored_groups.sort(key=lambda x: x[2], reverse=True)
        
        # Winner takes all
        winner_date, winner_results, _ = scored_groups[0]
        
        # If there's a tie or close second, prefer the earlier date
        # (conservative approach for trading)
        if len(scored_groups) > 1:
            _, _, second_score = scored_groups[1]
            _, _, first_score = scored_groups[0]
            
            if second_score >= first_score * 0.9:  # Within 10%
                # Pick earlier date
                dates = [
                    datetime.strptime(scored_groups[0][0], "%Y-%m-%d").date(),
                    datetime.strptime(scored_groups[1][0], "%Y-%m-%d").date()
                ]
                earlier = min(dates)
                winner_date = earlier.isoformat()
                # Find results for this date
                for d, r, _ in scored_groups:
                    if d == winner_date or (
                        abs((datetime.strptime(d, "%Y-%m-%d").date() - earlier).days) 
                        <= self.DATE_TOLERANCE_DAYS
                    ):
                        winner_results = r
                        break
        
        return winner_date, winner_results
    
    def _calculate_confidence(
        self, 
        agreeing_results: List[EarningsResult],
        all_valid_results: List[EarningsResult]
    ) -> int:
        """
        Calculate overall confidence score (0-100).
        
        Factors:
        - Source reliability weights
        - Number of agreeing sources
        - Proportion of sources agreeing
        """
        if not agreeing_results:
            return 0
        
        # Base: weighted sum of agreeing sources
        agreeing_weight = sum(r.confidence for r in agreeing_results)
        total_weight = sum(r.confidence for r in all_valid_results)
        
        if total_weight == 0:
            return 0
        
        # Weight ratio (0-1)
        weight_ratio = agreeing_weight / total_weight
        
        # Agreement ratio (0-1)
        agreement_ratio = len(agreeing_results) / len(all_valid_results)
        
        # Combined score
        # 60% weight on source reliability, 40% on agreement count
        score = (weight_ratio * 0.6 + agreement_ratio * 0.4) * 100
        
        # Bonus for multiple high-confidence sources agreeing
        if len(agreeing_results) >= 2:
            score = min(100, score + 10)
        
        return int(score)
    
    def _format_discrepancy(
        self, 
        date_groups: Dict[str, List[EarningsResult]]
    ) -> str:
        """Format discrepancy information for logging/display."""
        parts = []
        for date_str, results in sorted(date_groups.items()):
            sources = [r.source.value for r in results]
            parts.append(f"{date_str} ({', '.join(sources)})")
        return " vs ".join(parts)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_earnings_result(
    source: str,
    earnings_date: Optional[str],
    days_to_earnings: Optional[int],
    error: Optional[str] = None
) -> EarningsResult:
    """
    Create EarningsResult from raw data.
    
    Args:
        source: Source name (marketdata, yahoo_direct, yfinance)
        earnings_date: ISO date string or None
        days_to_earnings: Days until earnings or None
        error: Error message if fetch failed
        
    Returns:
        EarningsResult instance
    """
    try:
        source_enum = EarningsSource(source)
    except ValueError:
        source_enum = EarningsSource.YFINANCE  # Default fallback
    
    return EarningsResult(
        source=source_enum,
        earnings_date=earnings_date,
        days_to_earnings=days_to_earnings,
        success=error is None,
        error=error
    )


# Global aggregator instance
_aggregator: Optional[EarningsAggregator] = None


def get_earnings_aggregator() -> EarningsAggregator:
    """Get global aggregator instance."""
    global _aggregator
    if _aggregator is None:
        _aggregator = EarningsAggregator()
    return _aggregator
