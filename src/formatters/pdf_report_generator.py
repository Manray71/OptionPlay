# OptionPlay - PDF Report Generator
# ==================================
# Generates PDF reports using Jinja2 templates and WeasyPrint

import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass
class CoverPageData:
    """Data for the cover page."""
    date: str
    time: str
    title: str = "Bull-Put Spread"
    subtitle: str = ""

    # Stats
    symbols_after_filter: int = 0
    symbols_with_signals: int = 0
    vix_level: float = 0.0
    market_sentiment: str = "Neutral"

    # Parameters
    dte_range: str = "60-90 DTE"
    delta_short: str = "0.15-0.25"
    spread_width: str = "$5-$10"
    min_roi: str = ">30%"

    # VIX Regime
    vix_regime: str = "Normal"


@dataclass
class ScanResultRow:
    """Single row in scan results table."""
    rank: int
    symbol: str
    price: float
    change_pct: float
    score: float
    max_score: float
    strategy: str
    roi: float
    analyzed: bool = True


@dataclass
class ScoreItem:
    """Single score component."""
    label: str
    value: str
    color: str = "gray"  # green, orange, red, gray


@dataclass
class TradeLeg:
    """Option leg in trade setup."""
    leg_type: str  # "Short Put" or "Long Put"
    strike: float
    delta: float
    premium: float


@dataclass
class TradeSetup:
    """Complete trade setup."""
    short_leg: TradeLeg
    long_leg: TradeLeg
    net_credit: float
    max_risk: float
    roi: float
    breakeven: float
    prob_profit: float
    expiry_date: str
    dte: int
    earnings_days: Optional[int] = None


@dataclass
class SupportResistanceLevel:
    """S/R level with metadata."""
    rank: str  # S1, S2, R1, R2 etc.
    price: float
    distance_pct: float
    tests: int
    strength: float  # 0-100


@dataclass
class VolumeProfileBar:
    """Single bar in volume profile."""
    price: float
    volume_pct: float
    buy_pct: float
    sell_pct: float
    is_poc: bool = False
    is_current: bool = False


@dataclass
class VolumeProfileData:
    """Complete volume profile data."""
    bars: List[VolumeProfileBar]
    poc_price: float
    value_area: str
    hvn_support: float
    lvn_resistance: float
    price_step: str = "$2"


@dataclass
class FundamentalsData:
    """Fundamental data for a stock."""
    pe_ratio: Optional[float] = None
    market_cap: str = ""
    div_yield: str = "0.00%"
    iv_rank: int = 0
    earnings_in_days: Optional[int] = None
    sector: str = ""


@dataclass
class NewsItem:
    """Single news item."""
    text: str
    time: str
    sentiment: str = "neutral"  # positive, negative, neutral


@dataclass
class PriceLevel:
    """Price level for visualization."""
    label: str
    price: float
    pct_from_current: float
    level_type: str = "normal"  # resistance, current, short-strike, long-strike, support


@dataclass
class ScorecardData:
    """Complete data for one stock scorecard."""
    symbol: str
    company_name: str
    strategy: str  # pullback, bounce, breakout
    date: str
    dte: int

    # Price
    price: float
    price_change: float
    price_change_pct: float

    # Score
    score: float
    max_score: float
    score_items: List[ScoreItem]

    # Trade
    trade_setup: TradeSetup

    # Levels
    support_levels: List[SupportResistanceLevel]
    resistance_levels: List[SupportResistanceLevel]

    # Volume Profile
    volume_profile: VolumeProfileData

    # Price Visualization
    price_levels: List[PriceLevel]

    # Fundamentals
    fundamentals: FundamentalsData

    # News
    news: List[NewsItem]


@dataclass
class ReportData:
    """Complete report data."""
    cover: CoverPageData
    scan_results: List[ScanResultRow]
    scorecards: List[ScorecardData]


class PDFReportGenerator:
    """
    Generates PDF reports from scan data using Jinja2 and WeasyPrint.
    """

    def __init__(self, output_dir: str = "reports"):
        # Use absolute path to ensure write access in sandboxed environments
        if not os.path.isabs(output_dir):
            base_dir = os.environ.get("OPTIONPLAY_HOME", str(Path.home() / "OptionPlay"))
            output_dir = os.path.join(base_dir, output_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.template_path = TEMPLATE_DIR / "report_template.html"

    def _load_template(self) -> str:
        """Load the HTML template."""
        with open(self.template_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _format_price(self, price: float) -> str:
        """Format price with $ sign."""
        return f"${price:,.2f}"

    def _format_pct(self, pct: float, with_sign: bool = True) -> str:
        """Format percentage."""
        if with_sign:
            return f"{pct:+.1f}%"
        return f"{pct:.1f}%"

    def _get_change_class(self, value: float) -> str:
        """Get CSS class for positive/negative values."""
        return "up" if value >= 0 else "down"

    def _get_score_class(self, score: float, max_score: float) -> str:
        """Get CSS class for score level."""
        pct = score / max_score if max_score > 0 else 0
        if pct >= 0.6:
            return "high"
        elif pct >= 0.4:
            return "medium"
        return "low"

    def _render_cover_page(self, data: CoverPageData, scan_results: List[ScanResultRow]) -> str:
        """Render cover page HTML."""
        # Stats row
        sentiment_class = "green" if data.market_sentiment.lower() == "bullish" else (
            "red" if data.market_sentiment.lower() == "bearish" else "orange"
        )

        # Scan results table
        results_html = ""
        for row in scan_results:
            row_class = "analyzed" if row.analyzed else "not-analyzed"
            change_class = self._get_change_class(row.change_pct)
            roi_class = self._get_change_class(row.roi)

            results_html += f'''
              <tr class="{row_class}">
                <td>{row.rank}</td>
                <td class="symbol">{row.symbol}</td>
                <td class="price">{self._format_price(row.price)}</td>
                <td class="change {change_class}">{self._format_pct(row.change_pct)}</td>
                <td class="score">{row.score:.0f}/{row.max_score:.0f}</td>
                <td><span class="strategy-badge {row.strategy.lower()}">{row.strategy}</span></td>
                <td class="change {roi_class}">{self._format_pct(row.roi, False)}</td>
              </tr>
            '''

        return f'''
      <div class="cover-header">
        <div class="cover-logo">OptionPlay</div>
        <div class="cover-date">{data.date} · {data.time} EST</div>
      </div>

      <div class="cover-hero">
        <div class="cover-eyebrow">Market Scan Report</div>
        <div class="cover-title">{data.title.replace(" ", "<br>")}</div>
        <div class="cover-subtitle">{data.subtitle}</div>

        <div class="stats-row">
          <div class="stat-item">
            <div class="stat-value">{data.symbols_after_filter}</div>
            <div class="stat-label">Nach Earnings Filter</div>
          </div>
          <div class="stat-item">
            <div class="stat-value green">{data.symbols_with_signals}</div>
            <div class="stat-label">Werte mit Signalen</div>
          </div>
          <div class="stat-item">
            <div class="stat-value orange">{data.vix_level:.1f}</div>
            <div class="stat-label">VIX Level</div>
          </div>
          <div class="stat-item">
            <div class="stat-value {sentiment_class}">{data.market_sentiment}</div>
            <div class="stat-label">Markt Sentiment</div>
          </div>
        </div>

        <div class="params-section">
          <div class="params-title">Aktive Parameter</div>
          <div class="params-grid">
            <div class="param-item">
              <div class="param-value">{data.dte_range}</div>
              <div class="param-label">Laufzeit</div>
            </div>
            <div class="param-item">
              <div class="param-value">{data.delta_short}</div>
              <div class="param-label">Delta Short</div>
            </div>
            <div class="param-item">
              <div class="param-value">{data.spread_width}</div>
              <div class="param-label">Spread Width</div>
            </div>
            <div class="param-item">
              <div class="param-value">{data.min_roi}</div>
              <div class="param-label">Min ROI</div>
            </div>
          </div>
        </div>

        <div class="results-section">
          <div class="section-title">Scan Ergebnisse</div>
          <table class="results-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Symbol</th>
                <th>Preis</th>
                <th>Trend</th>
                <th>Score</th>
                <th>Strategie</th>
                <th>ROI</th>
              </tr>
            </thead>
            <tbody>
              {results_html}
            </tbody>
          </table>
        </div>
      </div>

      <div class="cover-footer">
        <div class="footer-left">OptionPlay Scanner · VIX Regime: {data.vix_regime}</div>
        <div class="footer-right">Seite 1</div>
      </div>
        '''

    def _render_score_grid(self, items: List[ScoreItem]) -> str:
        """Render score grid items."""
        html = ""
        for item in items:
            html += f'''
          <div class="score-item">
            <div class="score-item-value {item.color}">{item.value}</div>
            <div class="score-item-label">{item.label}</div>
          </div>
            '''
        return html

    def _render_volume_profile(self, vp: VolumeProfileData) -> str:
        """Render volume profile bars."""
        bars_html = ""
        for bar in vp.bars:
            row_class = "poc" if bar.is_poc else ("current-price" if bar.is_current else "")
            bar_class = "poc-bar" if bar.is_poc else ""

            bars_html += f'''
          <div class="volume-bar-row {row_class}">
            <span class="volume-bar-price">{self._format_price(bar.price)}</span>
            <div class="volume-bar-container">
              <div class="volume-bar-stacked {bar_class}" style="width: {bar.volume_pct:.0f}%;">
                <div class="buy-part" style="width: {bar.buy_pct:.0f}%;"></div>
                <div class="sell-part" style="width: {bar.sell_pct:.0f}%;"></div>
              </div>
            </div>
            <span class="volume-bar-pct">{bar.volume_pct:.1f}%</span>
          </div>
            '''

        return f'''
      <div class="volume-profile">
        <div class="volume-profile-title">Volume Profile <span class="volume-profile-subtitle">12 Monate · Preis je {vp.price_step}</span></div>
        <div class="volume-profile-bars">
          {bars_html}
        </div>
        <div class="volume-profile-legend">
          <div class="volume-legend-item">
            <div class="volume-legend-dot" style="background: var(--color-green);"></div>
            <span>Käufe</span>
          </div>
          <div class="volume-legend-item">
            <div class="volume-legend-dot" style="background: var(--color-red);"></div>
            <span>Verkäufe</span>
          </div>
          <div class="volume-legend-item">
            <div class="volume-legend-dot poc"></div>
            <span>POC</span>
          </div>
        </div>
        <div class="volume-profile-stats">
          <div class="volume-stat">
            <div class="volume-stat-value blue">{self._format_price(vp.poc_price)}</div>
            <div class="volume-stat-label">POC</div>
          </div>
          <div class="volume-stat">
            <div class="volume-stat-value">{vp.value_area}</div>
            <div class="volume-stat-label">Value Area</div>
          </div>
          <div class="volume-stat">
            <div class="volume-stat-value green">{self._format_price(vp.hvn_support)}</div>
            <div class="volume-stat-label">HVN Support</div>
          </div>
          <div class="volume-stat">
            <div class="volume-stat-value">{self._format_price(vp.lvn_resistance)}</div>
            <div class="volume-stat-label">LVN Resistance</div>
          </div>
        </div>
      </div>
        '''

    def _render_scorecard_page1(self, card: ScorecardData, page_num: int) -> str:
        """Render first page of scorecard."""
        change_class = self._get_change_class(card.price_change)
        score_class = self._get_score_class(card.score, card.max_score)
        score_pct = (card.score / card.max_score * 100) if card.max_score > 0 else 0

        # Trade setup
        ts = card.trade_setup

        # Support levels
        support_html = ""
        for lvl in card.support_levels[:3]:
            strength_pct = min(lvl.strength, 100)
            support_html += f'''
          <div class="level-item">
            <div class="level-left">
              <span class="level-rank">{lvl.rank}</span>
              <span class="level-price">{self._format_price(lvl.price)}</span>
            </div>
            <div class="level-right">
              <span class="level-distance">{self._format_pct(lvl.distance_pct)}</span>
              <div class="level-tests">
                <span class="level-tests-count">{lvl.tests}x</span>
                <div class="level-strength"><div class="level-strength-fill" style="width: {strength_pct:.0f}%; background: var(--color-green);"></div></div>
              </div>
            </div>
          </div>
            '''

        # Resistance levels
        resistance_html = ""
        for lvl in card.resistance_levels[:3]:
            strength_pct = min(lvl.strength, 100)
            resistance_html += f'''
          <div class="level-item">
            <div class="level-left">
              <span class="level-rank">{lvl.rank}</span>
              <span class="level-price">{self._format_price(lvl.price)}</span>
            </div>
            <div class="level-right">
              <span class="level-distance">{self._format_pct(lvl.distance_pct)}</span>
              <div class="level-tests">
                <span class="level-tests-count">{lvl.tests}x</span>
                <div class="level-strength"><div class="level-strength-fill" style="width: {strength_pct:.0f}%; background: var(--color-red);"></div></div>
              </div>
            </div>
          </div>
            '''

        earnings_display = f"{ts.earnings_days}d" if ts.earnings_days else "N/A"

        return f'''
    <div class="scorecard">
      <div class="stock-hero">
        <div class="stock-header-row">
          <div class="stock-info">
            <div class="stock-symbol">{card.symbol}</div>
            <div class="stock-name">{card.company_name}</div>
          </div>
          <div class="stock-meta">
            <div class="stock-strategy {card.strategy.lower()}">{card.strategy}</div>
            <div class="stock-date">{card.date} · {card.dte} DTE</div>
          </div>
        </div>
        <div class="price-display">
          <span class="price-value">{self._format_price(card.price)}</span>
          <span class="price-change {change_class}">{self._format_price(abs(card.price_change)).replace("$", "-$" if card.price_change < 0 else "+$")}</span>
          <span class="price-change-percent">({self._format_pct(card.price_change_pct)})</span>
        </div>
      </div>

      <div class="score-section">
        <div class="score-header">
          <div class="score-title">Signal Score</div>
          <div class="score-value {score_class}">{card.score:.0f} / {card.max_score:.0f}</div>
        </div>
        <div class="score-bar">
          <div class="score-bar-fill {score_class}" style="width: {score_pct:.0f}%;"></div>
        </div>
        <div class="score-grid">
          {self._render_score_grid(card.score_items)}
        </div>
      </div>

      <div class="trade-ticket">
        <div class="ticket-header">
          <div class="ticket-title">Bull-Put Spread Setup</div>
          <div class="ticket-expiry-prominent">
            <span class="expiry-label">Verfall</span>
            <span class="expiry-date">{ts.expiry_date}</span>
            <span class="expiry-dte">{ts.dte} DTE</span>
          </div>
        </div>
        <div class="trade-legs">
          <div class="trade-leg short">
            <div class="leg-type">Short Put</div>
            <div class="leg-strike">{self._format_price(ts.short_leg.strike)}</div>
            <div class="leg-delta"><span class="delta-symbol">Δ</span> {abs(ts.short_leg.delta):.2f}</div>
          </div>
          <div class="trade-arrow">→</div>
          <div class="trade-leg long">
            <div class="leg-type">Long Put</div>
            <div class="leg-strike">{self._format_price(ts.long_leg.strike)}</div>
            <div class="leg-delta"><span class="delta-symbol">Δ</span> {abs(ts.long_leg.delta):.2f}</div>
          </div>
          <div class="trade-arrow">=</div>
          <div class="trade-result">
            <div class="result-label">Net Credit</div>
            <div class="result-value">{self._format_price(ts.net_credit)}</div>
          </div>
        </div>
        <div class="ticket-metrics">
          <div class="metric">
            <div class="metric-value red">{self._format_price(ts.max_risk)}</div>
            <div class="metric-label">Margin</div>
          </div>
          <div class="metric">
            <div class="metric-value">{self._format_price(ts.breakeven)}</div>
            <div class="metric-label">Break-Even</div>
          </div>
          <div class="metric">
            <div class="metric-value green">{ts.roi:.1f}%</div>
            <div class="metric-label">ROI</div>
          </div>
          <div class="metric">
            <div class="metric-value green">~{ts.prob_profit:.0f}%</div>
            <div class="metric-label">P(Profit)</div>
          </div>
          <div class="metric">
            <div class="metric-value green">{earnings_display}</div>
            <div class="metric-label">Earnings</div>
          </div>
        </div>
      </div>

      <div class="levels-row">
        <div class="levels-card">
          <div class="levels-header">
            <div class="levels-title support"><span class="dot"></span> Support (12M)</div>
            <div class="levels-tested">getestet</div>
          </div>
          {support_html}
        </div>

        <div class="levels-card">
          <div class="levels-header">
            <div class="levels-title resistance"><span class="dot"></span> Resistance (12M)</div>
            <div class="levels-tested">getestet</div>
          </div>
          {resistance_html}
        </div>
      </div>

      {self._render_volume_profile(card.volume_profile)}

      <div class="page-footer">
        <span>{card.symbol} · Scorecard 1/2</span>
        <span>Seite {page_num}</span>
      </div>
    </div>
        '''

    def _render_scorecard_page2(self, card: ScorecardData, page_num: int) -> str:
        """Render second page of scorecard."""
        # Price levels visualization
        levels_html = ""
        for lvl in card.price_levels:
            levels_html += f'''
          <div class="price-level {lvl.level_type}">
            <span class="price-level-label">{lvl.label}</span>
            <span class="price-level-value">{self._format_price(lvl.price)}</span>
            <div class="price-level-bar" style="width: {max(10, 100 - abs(lvl.pct_from_current) * 5):.0f}%;"></div>
          </div>
            '''

        # Fundamentals
        fd = card.fundamentals
        pe_display = f"{fd.pe_ratio:.1f}" if fd.pe_ratio else "N/A"
        earnings_class = "green" if fd.earnings_in_days and fd.earnings_in_days > 45 else "orange"
        earnings_display = f"{fd.earnings_in_days} Tage" if fd.earnings_in_days else "N/A"

        # News
        news_html = ""
        for item in card.news[:3]:
            sentiment_icon = "+" if item.sentiment == "positive" else ("-" if item.sentiment == "negative" else "○")
            news_html += f'''
        <div class="news-item">
          <span class="news-sentiment {item.sentiment}">{sentiment_icon}</span>
          <div class="news-content">
            <div class="news-text">{item.text}</div>
            <div class="news-time">{item.time}</div>
          </div>
        </div>
            '''

        return f'''
    <div class="scorecard">
      <div class="stock-hero" style="margin-bottom: var(--space-3);">
        <div class="stock-header-row">
          <div class="stock-info">
            <div class="stock-symbol">{card.symbol}</div>
            <div class="stock-name">{card.company_name} · Fortsetzung</div>
          </div>
          <div class="stock-meta">
            <div class="stock-strategy {card.strategy.lower()}">{card.strategy}</div>
          </div>
        </div>
      </div>

      <div class="price-viz">
        <div class="price-viz-title">Price & Strike Levels</div>
        <div class="price-viz-chart">
          {levels_html}
        </div>
      </div>

      <div class="fundamentals">
        <div class="fundamentals-title">Fundamentals</div>
        <div class="fundamentals-grid">
          <div class="fundamental-item">
            <div class="fundamental-value">{pe_display}</div>
            <div class="fundamental-label">P/E Ratio</div>
          </div>
          <div class="fundamental-item">
            <div class="fundamental-value">{fd.market_cap}</div>
            <div class="fundamental-label">Market Cap</div>
          </div>
          <div class="fundamental-item">
            <div class="fundamental-value">{fd.div_yield}</div>
            <div class="fundamental-label">Div Yield</div>
          </div>
          <div class="fundamental-item">
            <div class="fundamental-value">{fd.iv_rank}</div>
            <div class="fundamental-label">IV Rank</div>
          </div>
          <div class="fundamental-item {earnings_class}">
            <div class="fundamental-value">{earnings_display}</div>
            <div class="fundamental-label">Earnings in</div>
          </div>
          <div class="fundamental-item">
            <div class="fundamental-value">{fd.sector}</div>
            <div class="fundamental-label">Sector</div>
          </div>
        </div>
      </div>

      <div class="news-section">
        <div class="news-title">Aktuelle News</div>
        {news_html}
      </div>

      <div class="page-footer">
        <span>{card.symbol} · Scorecard 2/2</span>
        <span>Seite {page_num}</span>
      </div>
    </div>
        '''

    def render_html(self, data: ReportData) -> str:
        """
        Render complete HTML report from data.

        Args:
            data: Complete report data

        Returns:
            HTML string
        """
        # Load template and extract CSS
        template = self._load_template()

        # Extract style section
        style_start = template.find('<style>')
        style_end = template.find('</style>') + len('</style>')
        css = template[style_start:style_end]

        # Build pages
        pages = []

        # Cover page
        cover_html = f'''
  <div class="page">
    <div class="cover">
      {self._render_cover_page(data.cover, data.scan_results)}
    </div>
  </div>
        '''
        pages.append(cover_html)

        # Scorecard pages
        page_num = 2
        for card in data.scorecards:
            # Page 1 of scorecard
            pages.append(f'''
  <div class="page">
    {self._render_scorecard_page1(card, page_num)}
  </div>
            ''')
            page_num += 1

            # Page 2 of scorecard
            pages.append(f'''
  <div class="page">
    {self._render_scorecard_page2(card, page_num)}
  </div>
            ''')
            page_num += 1

        # Assemble final HTML
        html = f'''<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OptionPlay Market Scan Report</title>
  {css}
</head>
<body>
{"".join(pages)}
</body>
</html>
'''
        return html

    def generate_pdf(self, data: ReportData, filename: Optional[str] = None) -> Path:
        """
        Generate PDF from report data.

        Args:
            data: Complete report data
            filename: Optional filename (without extension)

        Returns:
            Path to generated PDF
        """
        try:
            from weasyprint import HTML, CSS
        except ImportError:
            raise ImportError("WeasyPrint is required. Install with: pip install weasyprint")

        # Generate filename if not provided
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"scan_report_{timestamp}"

        # Render HTML
        html_content = self.render_html(data)

        # Save HTML for debugging
        html_path = self.output_dir / f"{filename}.html"
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # Generate PDF
        pdf_path = self.output_dir / f"{filename}.pdf"

        try:
            html_doc = HTML(string=html_content, base_url=str(TEMPLATE_DIR))
            html_doc.write_pdf(pdf_path)
            logger.info(f"PDF generated: {pdf_path}")
        except Exception as e:
            logger.error(f"PDF generation failed: {e}")
            raise

        return pdf_path


# Convenience function
def generate_scan_report_pdf(
    vix_level: float,
    scan_results: List[Dict[str, Any]],
    scorecards_data: List[Dict[str, Any]],
    market_sentiment: str = "Neutral",
    output_dir: str = "reports",
) -> Path:
    """
    Convenience function to generate a scan report PDF.

    Args:
        vix_level: Current VIX level
        scan_results: List of scan result dicts
        scorecards_data: List of scorecard data dicts
        market_sentiment: Market sentiment string
        output_dir: Output directory

    Returns:
        Path to generated PDF
    """
    generator = PDFReportGenerator(output_dir)

    # Build cover data
    now = datetime.now()
    cover = CoverPageData(
        date=now.strftime("%d. %B %Y").replace("January", "Januar").replace("February", "Februar"),
        time=now.strftime("%H:%M"),
        vix_level=vix_level,
        market_sentiment=market_sentiment,
        symbols_after_filter=len(scan_results),
        symbols_with_signals=len([r for r in scan_results if r.get('analyzed', True)]),
    )

    # Convert scan results
    results = []
    for i, r in enumerate(scan_results, 1):
        results.append(ScanResultRow(
            rank=i,
            symbol=r['symbol'],
            price=r['price'],
            change_pct=r.get('change_pct', 0),
            score=r['score'],
            max_score=r.get('max_score', 16),
            strategy=r['strategy'],
            roi=r.get('roi', 0),
            analyzed=r.get('analyzed', True),
        ))

    # Convert scorecards (simplified - full conversion would need more data)
    scorecards = []
    for sc in scorecards_data:
        # This is a simplified conversion - real implementation would parse all fields
        pass

    data = ReportData(
        cover=cover,
        scan_results=results,
        scorecards=scorecards,
    )

    return generator.generate_pdf(data)
