# Earnings Dip Analyzer — Literaturbasierte Code-Verbesserungen

## Übersicht

Basierend auf der Analyse der akademischen Literatur (PEAD, Overreaction Reversal, Mean-Reversion) sind hier die konkreten Code-Änderungen für `src/analyzers/earnings_dip.py` und `config/analyzer_thresholds.yaml`.

**Prioritäten:**
- 🔴 P1 — Höchste Impact-Änderungen (Sektor-Kontext, relative Dip-Schwellen)
- 🟡 P2 — Wichtige Verbesserungen (Timing, Penalty-Anpassung)
- 🟢 P3 — Nice-to-have (Value-Check, zusätzliche Indikatoren)

---

## 🔴 P1: Relative Dip-Schwellen statt absoluter Prozent-Werte

### Problem
Feste Schwellen (5–25%) behandeln alle Aktien gleich. Ein 10% Drop bei JNJ (historische Earnings-Volatilität ~3%) ist dramatischer als bei NVDA (~8%).

### Literatur-Basis
- SUE (Standardized Unexpected Earnings) ist der akademische Standard seit Bernard & Thomas (1989)
- Da, Liu & Schaumburg (2014): Residual-basierte Reversal-Strategien sind 4× profitabler als Standard-Reversals

### Code-Änderung: `src/analyzers/earnings_dip.py`

```python
# NEUE METHODE: Berechne historische Earnings-Move-Volatilität
def _calculate_earnings_move_zscore(self, dip_pct: float, historical_data: dict) -> float:
    """
    Berechnet den Z-Score des aktuellen Dips relativ zur 
    historischen Earnings-Reaktion der Aktie.
    
    Literatur: SUE-Konzept (Bernard & Thomas 1989/1990)
    Ein Z-Score > 2.0 deutet auf Overreaction hin.
    """
    # Historischer Durchschnitt der Earnings-Moves (absolut)
    avg_earnings_move = historical_data.get('avg_earnings_move_pct', None)
    std_earnings_move = historical_data.get('std_earnings_move_pct', None)
    
    if avg_earnings_move is None or std_earnings_move is None or std_earnings_move == 0:
        return None  # Fallback auf absolute Schwellen
    
    z_score = (dip_pct - avg_earnings_move) / std_earnings_move
    return z_score
```

```python
# ANPASSUNG in _score_drop_magnitude():
def _score_drop_magnitude(self, dip_pct: float, historical_data: dict = None) -> float:
    """
    Drop Magnitude Score — jetzt mit optionaler Z-Score-Normalisierung.
    Fallback: Bisherige absolute Schwellen wenn keine historischen Daten.
    """
    score = 0.0
    
    # Versuche relative Bewertung (bevorzugt)
    z_score = None
    if historical_data:
        z_score = self._calculate_earnings_move_zscore(dip_pct, historical_data)
    
    if z_score is not None:
        # Z-Score-basierte Bewertung (Literatur-konform)
        if z_score >= 3.0:
            score = 1.0   # Extrem — möglicherweise fundamental (reduziert wie >20%)
        elif z_score >= 2.0:
            score = 2.0   # Ideal: Klar übertriebene Reaktion
        elif z_score >= 1.5:
            score = 1.5   # Gut: Deutlich über normal
        elif z_score >= 1.0:
            score = 1.0   # Moderat: Etwas übertrieben
        else:
            score = 0.5   # Klein: Nahe am normalen Earnings-Move
    else:
        # Fallback: Bestehende absolute Schwellen (unverändert)
        if dip_pct > self.cfg.get('max_dip_pct', 20.0):
            score = 1.0
        elif dip_pct >= 15.0:
            score = 2.0
        elif dip_pct >= 10.0:
            score = 1.5
        elif dip_pct >= 7.0:
            score = 1.0
        else:
            score = 0.5
    
    return score
```

### Config-Änderung: `config/analyzer_thresholds.yaml`

```yaml
earnings_dip:
  # NEU: Z-Score-basierte Bewertung (bevorzugt, wenn historische Daten verfügbar)
  relative_scoring:
    enabled: true
    extreme_zscore: 3.0    # Darüber: möglicherweise fundamental
    ideal_zscore: 2.0      # Sweet-Spot für Overreaction
    good_zscore: 1.5
    moderate_zscore: 1.0
    
  # Bestehende absolute Schwellen als Fallback (unverändert)
  min_dip_pct: 5.0
  max_dip_pct: 20.0
  extreme_dip_pct: 25.0
```

---

## 🔴 P1: Sektor-Kontext-Indikator

### Problem
Der "Sector Stable" Overreaction-Indikator ist als Placeholder markiert aber nicht implementiert. Laut Hameed & Mian (2015) sind firmenspezifische Drops in einem stabilen Sektor die profitabelsten Reversal-Kandidaten.

### Literatur-Basis
- Hameed & Mian (2015): Intra-industry Reversal-Strategien outperformen Standard-Reversals signifikant
- Da, Liu & Schaumburg (2014): Residual-Returns (nach Abzug des Sektor-Effekts) haben die stärksten Reversals

### Code-Änderung: `src/analyzers/earnings_dip.py`

```python
# NEUE METHODE: Sektor-Kontext prüfen
def _check_sector_context(self, symbol: str, dip_period_days: int = 5) -> dict:
    """
    Prüft ob der Dip firmenspezifisch oder sektorgetrieben ist.
    
    Literatur: Hameed & Mian (2015) - firmenspezifische Drops
    in stabilem Sektor haben stärkste Mean-Reversion.
    
    Returns:
        dict mit:
        - sector_stable: bool — Sektor war im gleichen Zeitraum stabil
        - sector_return_pct: float — Sektor-Performance im Dip-Zeitraum
        - residual_dip_pct: float — Firmenspezifischer Dip (nach Sektor-Abzug)
    """
    from ..data.watchlist import get_sector_for_symbol, get_sector_etf
    
    sector = get_sector_for_symbol(symbol)
    if not sector:
        return {'sector_stable': None, 'sector_return_pct': None, 'residual_dip_pct': None}
    
    sector_etf = get_sector_etf(sector)  # z.B. XLK für Technology
    if not sector_etf:
        return {'sector_stable': None, 'sector_return_pct': None, 'residual_dip_pct': None}
    
    try:
        # Hole Sektor-Performance im gleichen Zeitraum
        sector_data = self.data_provider.get_historical(sector_etf, days=dip_period_days + 5)
        if not sector_data or len(sector_data) < dip_period_days:
            return {'sector_stable': None, 'sector_return_pct': None, 'residual_dip_pct': None}
        
        # Sektor-Return im Dip-Zeitraum
        sector_closes = [d['close'] for d in sector_data[-dip_period_days:]]
        sector_return_pct = ((sector_closes[-1] / sector_closes[0]) - 1) * 100
        
        # Sektor gilt als stabil wenn er weniger als 3% gefallen ist
        sector_stable = sector_return_pct > -3.0
        
        # Residual Dip = Firmen-Dip minus Sektor-Move
        # (Wenn Sektor -5% und Aktie -12%, dann residual = -7%)
        residual_dip_pct = None  # Wird vom Caller berechnet
        
        return {
            'sector_stable': sector_stable,
            'sector_return_pct': round(sector_return_pct, 2),
            'residual_dip_pct': residual_dip_pct
        }
    except Exception as e:
        logger.warning(f"Sector context check failed for {symbol}: {e}")
        return {'sector_stable': None, 'sector_return_pct': None, 'residual_dip_pct': None}


# HILFSFUNKTION: Sektor-ETF Mapping
# In src/data/watchlist.py oder als Teil der bestehenden Watchlist-Config
SECTOR_ETF_MAP = {
    'Technology': 'XLK',
    'Healthcare': 'XLV', 
    'Financials': 'XLF',
    'Consumer Discretionary': 'XLY',
    'Consumer Staples': 'XLP',
    'Industrials': 'XLI',
    'Energy': 'XLE',
    'Materials': 'XLB',
    'Real Estate': 'XLRE',
    'Utilities': 'XLU',
    'Communication Services': 'XLC',
}
```

```python
# ANPASSUNG in _score_overreaction():
def _score_overreaction(self, analysis_data: dict) -> float:
    """Overreaction Indicators — jetzt MIT Sektor-Kontext."""
    score = 0.0
    indicators = []
    
    # Bestehende Indikatoren (unverändert)
    rsi = analysis_data.get('rsi')
    if rsi is not None and rsi < self.cfg.get('rsi_extreme_oversold', 30):
        score += 0.5
        indicators.append('RSI extreme oversold')
    
    panic_volume = analysis_data.get('panic_volume', False)
    if panic_volume:
        score += 0.5
        indicators.append('Panic volume')
    
    historical_overreaction = analysis_data.get('historical_overreaction', False)
    if historical_overreaction:
        score += 0.5
        indicators.append('Historical overreaction')
    
    # NEU: Sektor-Kontext-Indikator (ersetzt den bisherigen Placeholder)
    sector_ctx = analysis_data.get('sector_context', {})
    sector_stable = sector_ctx.get('sector_stable')
    if sector_stable is True:
        score += 0.5
        indicators.append(f"Sector stable ({sector_ctx.get('sector_return_pct', '?')}%)")
    elif sector_stable is False:
        # Sektor fällt auch → reduziere Overreaction-Vermutung
        # KEIN Punkt, und optional Warning
        indicators.append(f"⚠️ Sector also declining ({sector_ctx.get('sector_return_pct', '?')}%)")
    
    return min(score, 2.0), indicators
```

### Config-Änderung

```yaml
earnings_dip:
  overreaction:
    # Bestehend
    rsi_extreme_oversold: 30
    panic_volume_multiplier: 3.0
    historical_move_multiplier: 2.0
    # NEU
    sector_stability_threshold: -3.0  # Sektor gilt als stabil wenn > -3%
```

---

## 🟡 P2: Stabilisierungs-Timing anpassen

### Problem
`min_stabilization_days = 1` ist zu aggressiv. Die Literatur zeigt, dass die profitabelsten Entries nach Abklingen der initialen Volatilität kommen, typischerweise 2–5 Tage nach dem Drop.

### Literatur-Basis
- So & Wang (2014): 6-facher Anstieg kurzfristiger Reversals während Earnings-Perioden, aber die meisten sind Noise
- Milian (2015): Profitablere Reversals bei Aktien, die Zeit zur Stabilisierung hatten

### Code-Änderung

```python
# ANPASSUNG: Dynamisches Stabilisierungs-Fenster basierend auf Drop-Größe
def _get_min_stabilization_days(self, dip_pct: float) -> int:
    """
    Größere Drops brauchen mehr Zeit zur Stabilisierung.
    
    Literatur: So & Wang (2014) — initiale Post-Earnings Volatilität
    dauert typischerweise 2-3 Tage, bei großen Drops länger.
    """
    if dip_pct >= 15.0:
        return 3  # Große Drops: 3 Tage minimum
    elif dip_pct >= 10.0:
        return 2  # Moderate Drops: 2 Tage
    else:
        return 2  # Kleine Drops: auch 2 Tage (von 1 erhöht)


# ANPASSUNG in der Stabilization-Check-Logik:
# Ersetze den festen min_stabilization_days Check:
# ALT:
#   if days_since_drop < self.cfg.get('min_stabilization_days', 1):
# NEU:
min_stab_days = self._get_min_stabilization_days(dip_pct)
if days_since_drop < min_stab_days:
    return None, f"Too early — need {min_stab_days} days for stabilization (have {days_since_drop})"
```

### Config-Änderung

```yaml
earnings_dip:
  stabilization:
    # ALT: min_stabilization_days: 1
    # NEU: Dynamisch basierend auf Drop-Größe
    min_stabilization_days_small: 2   # Dip < 10%
    min_stabilization_days_moderate: 2 # Dip 10-15%
    min_stabilization_days_large: 3    # Dip > 15%
```

---

## 🟡 P2: Continued-Decline Penalty entschärfen

### Problem
-1.5 Penalty bei nur 2 neuen Tiefs ist zu streng. In einem 10-Tage-Fenster nach einem Earnings-Drop sind 2 leicht niedrigere Tiefs bei volatilen Aktien normal, besonders in den ersten 2-3 Tagen.

### Literatur-Basis
- Die Literatur unterscheidet "orderly price discovery" (normal nach großen Events) von "panic continuation"
- PEAD-Forschung zeigt, dass moderate weiterer Drift in den ersten Tagen normal ist

### Code-Änderung

```python
# ALT: Zähle einfach neue Tiefs
# NEU: Bewerte MAGNITUDE und TIMING der neuen Tiefs
def _calculate_continued_decline_penalty(self, prices_after_drop: list, 
                                           dip_low: float,
                                           dip_pct: float) -> float:
    """
    Verfeinerte Continued-Decline-Penalty.
    
    Unterscheidet zwischen:
    1. Orderly price discovery (leichte neue Tiefs, ≤2% unter Dip-Low) → milde Strafe
    2. Panic continuation (deutliche neue Tiefs, >2% unter Dip-Low) → volle Strafe
    3. Accelerating decline (3+ neue Tiefs mit steigender Magnitude) → maximale Strafe
    """
    if not prices_after_drop or dip_low <= 0:
        return 0.0
    
    new_lows = []
    for p in prices_after_drop:
        low = p.get('low', p.get('close'))
        if low < dip_low:
            decline_below_dip = ((dip_low - low) / dip_low) * 100
            new_lows.append(decline_below_dip)
    
    if len(new_lows) < 2:
        return 0.0  # 0-1 neue Tiefs: kein Problem
    
    max_decline_below_dip = max(new_lows)
    
    # Milde neue Tiefs (≤2% unter Dip-Low): Orderly price discovery
    if max_decline_below_dip <= 2.0:
        return -0.5  # Mild statt -1.5
    
    # Moderate neue Tiefs (2-5% unter Dip-Low)
    elif max_decline_below_dip <= 5.0:
        return -1.0
    
    # Starke neue Tiefs (>5% unter Dip-Low) oder 3+ neue Tiefs: Panic continuation
    elif len(new_lows) >= 3 or max_decline_below_dip > 5.0:
        return -1.5
    
    return -1.0  # Default moderate Strafe
```

### Config-Änderung

```yaml
earnings_dip:
  penalties:
    continued_decline:
      # ALT: Pauschal -1.5 bei 2 neuen Tiefs
      # NEU: Abgestuft nach Magnitude
      mild_threshold_pct: 2.0      # ≤2% unter Dip-Low = orderly
      mild_penalty: -0.5
      moderate_threshold_pct: 5.0  # 2-5% unter Dip-Low
      moderate_penalty: -1.0
      severe_penalty: -1.5         # >5% oder 3+ neue Tiefs
      new_lows_min: 2              # Unverändert: min 2 für Penalty
    under_sma200: -1.0             # Unverändert
    rsi_not_extreme: -0.5          # Siehe P2 unten
    penalty_max: -3.0              # Unverändert
```

---

## 🟡 P2: RSI > 40 Penalty überdenken

### Problem
RSI > 40 wird mit -0.5 bestraft. Aber nach einem Earnings-Drop kann RSI > 40 bedeuten, dass die Aktie bereits Recovery-Dynamik zeigt. Die Literatur sieht RSI 40-50 in einem Aufwärtstrend sogar als Kaufzone.

### Literatur-Basis
- Wilder (1978), Constance Brown: In Bullenmärkten ist RSI 40-50 die Unterstützungszone
- RSI Failure-Swing-Strategie: Kaufsignal wenn RSI aus Oversold zurückkommt und über 30 bleibt

### Code-Änderung

```python
# ANPASSUNG in _calculate_penalties():
def _calculate_rsi_penalty(self, rsi: float, was_above_sma200_before_dip: bool) -> float:
    """
    RSI-Penalty nur anwenden wenn RSI deutlich über Oversold UND
    die Aktie nicht in einem intakten Aufwärtstrend war.
    
    Logik: 
    - Aktie war über SMA200 → RSI 40-50 ist Recovery-Signal, KEIN Penalty
    - Aktie war unter SMA200 → RSI > 40 = nicht oversold genug, Penalty
    """
    if rsi is None:
        return 0.0
    
    rsi_threshold = self.cfg.get('rsi_moderate_oversold', 40)
    
    if rsi <= rsi_threshold:
        return 0.0  # Oversold genug, kein Penalty
    
    # NEU: Wenn Aktie im Aufwärtstrend war (über SMA200), 
    # ist höherer RSI eher ein Recovery-Signal
    if was_above_sma200_before_dip:
        # Nur bestrafen wenn RSI wirklich hoch ist (>55 = kaum oversold)
        if rsi > 55:
            return -0.5
        else:
            return 0.0  # RSI 40-55 bei Quality-Aktie = Recovery, kein Penalty
    
    # Aktie war bereits im Downtrend: Strengerer Standard
    return -0.5
```

---

## 🟢 P3: Value/Glamour-Check

### Problem
Die Literatur zeigt konsistent, dass Value-Aktien (niedrige Bewertung) nach Earnings-Drops stärkere Reversals haben als Glamour-Aktien (hohe Bewertung).

### Literatur-Basis
- Skinner & Sloan (2002): Glamour-Stocks werden nach Earnings-Misses überproportional bestraft
- Value/Glamour-PEAD Paper: Value-Portfolios haben fast immer höhere Post-Earnings Abnormal Returns

### Code-Änderung

```python
# NEUER optionaler Bonus in _score_fundamental_strength():
def _score_value_bonus(self, symbol: str) -> float:
    """
    Optionaler Value-Bonus für die Fundamental-Bewertung.
    
    Value-Aktien (niedrige PE/PB) erholen sich nach 
    Earnings-Drops stärker als Glamour-Aktien.
    
    Literatur: Skinner & Sloan (2002), Value-Glamour PEAD
    
    Returns: 0.0 bis 0.5 Bonus
    """
    # PE-Ratio aus verfügbaren Daten (Yahoo Finance, IBKR)
    pe_ratio = self._get_pe_ratio(symbol)
    
    if pe_ratio is None:
        return 0.0
    
    # Value-Aktie: PE unter Sektor-Median → Recovery wahrscheinlicher
    # Glamour-Aktie: PE deutlich über Sektor-Median → Vorsicht
    if pe_ratio < 15:
        return 0.5   # Deep Value → starker Recovery-Bonus
    elif pe_ratio < 25:
        return 0.25  # Moderate Value
    elif pe_ratio > 50:
        return -0.25 # Glamour-Penalty (Skinner & Sloan Effekt)
    
    return 0.0
```

**Hinweis:** Diese Metrik ist optional und sollte nur aktiviert werden wenn PE-Daten zuverlässig verfügbar sind. Kann über Config toggle gesteuert werden.

---

## 🟢 P3: Target-Berechnung verfeinern

### Problem
Das fixe 50% Recovery-Target ist konservativ. Die Literatur zeigt, dass die Recovery-Rate von der Drop-Ursache abhängt.

### Code-Änderung

```python
# ANPASSUNG der Target-Berechnung:
def _calculate_target(self, entry_price: float, pre_earnings_price: float, 
                       signal_strength: str, sector_stable: bool = None) -> float:
    """
    Dynamisches Recovery-Target basierend auf Signal-Stärke und Kontext.
    
    Literatur: 
    - Firmenspezifische Overreactions erholen sich stärker (Hameed & Mian 2015)
    - Starke Signale korrelieren mit höherer Recovery-Rate
    """
    dip_size = pre_earnings_price - entry_price
    
    if signal_strength == 'Strong' and sector_stable:
        recovery_pct = 0.65  # Starkes Signal + stabiler Sektor → 65% Recovery
    elif signal_strength == 'Strong':
        recovery_pct = 0.55  # Starkes Signal → 55%
    elif signal_strength == 'Moderate':
        recovery_pct = 0.50  # Standard → 50% (unverändert)
    else:
        recovery_pct = 0.40  # Schwaches Signal → konservativer
    
    target = entry_price + (dip_size * recovery_pct)
    return round(target, 2)
```

---

## Zusammenfassung: Gesamtauswirkung auf Score-Berechnung

### Vorher (Max 9.5)
| Komponente | Max | Erreichbar |
|-----------|-----|-----------|
| Drop Magnitude | 2.0 | 2.0 |
| Stabilization | 2.5 | 2.5 |
| Fundamental | 2.0 | 2.0 |
| Overreaction | 2.0 | **1.5** (Sector fehlt) |
| BPS Suitability | 1.0 | **0.5** (IV fehlt) |
| **Erreichbar** | **9.5** | **8.5** |

### Nachher (Max 9.5, aber realistischer erreichbar)
| Komponente | Max | Erreichbar |
|-----------|-----|-----------|
| Drop Magnitude | 2.0 | 2.0 (Z-Score-basiert) |
| Stabilization | 2.5 | 2.5 (besseres Timing) |
| Fundamental | 2.0 | 2.0 (+0.5 Value-Bonus möglich, Cap bleibt 2.0) |
| Overreaction | 2.0 | **2.0** ✅ (Sector implementiert) |
| BPS Suitability | 1.0 | 0.5 (IV weiterhin TODO) |
| **Erreichbar** | **9.5** | **9.0** |

### Penalty-Änderungen
| Penalty | Vorher | Nachher |
|---------|--------|---------|
| Continued Decline | -1.5 (pauschal bei 2 Tiefs) | -0.5 bis -1.5 (abgestuft) |
| RSI not extreme | -0.5 (RSI > 40) | -0.5 nur bei RSI > 55 in Uptrend-Aktien |
| Under SMA200 | -1.0 | -1.0 (unverändert) |

---

## Implementierungs-Reihenfolge

1. **Sektor-Kontext** (P1) — Höchster Edge laut Literatur, relativ einfach da Sektor-ETF-Daten bereits über bestehende Data-Provider verfügbar
2. **Continued-Decline Penalty** (P2) — Schneller Fix, verhindert fälschliche Disqualifikation guter Setups
3. **Stabilisierungs-Timing** (P2) — Config-Änderung + kleine Code-Anpassung
4. **RSI Penalty** (P2) — Kleine Logik-Änderung
5. **Relative Dip-Schwellen** (P1) — Braucht historische Earnings-Move-Daten, höherer Aufwand
6. **Value-Bonus** (P3) — Optional, abhängig von PE-Daten-Verfügbarkeit
7. **Dynamisches Target** (P3) — Letzte Priorität, einfache Anpassung

---

## Neue Warnings

```python
# Ergänze bestehende Warning-Liste:
NEW_WARNINGS = {
    'sector_declining': "⚠️ Sector also declining ({sector_return_pct}%) — may not be overreaction",
    'low_zscore': "ℹ️ Dip within normal earnings range (Z-Score: {zscore:.1f})",
    'early_entry': "ℹ️ Aggressive timing — only {days} days since drop (recommend {min_days}+)",
    'glamour_stock': "⚠️ High PE ({pe}) — glamour stocks recover slower (Skinner & Sloan)",
}
```

---

## Tests

Jede Änderung sollte gegen bestehende Test-Cases validiert werden. Zusätzliche Test-Szenarien:

```python
# test_earnings_dip_improvements.py

def test_relative_dip_scoring():
    """Z-Score-basierte Bewertung bevorzugt relative über absolute Schwellen."""
    # NVDA: 10% Drop bei avg_earnings_move=8%, std=3% → Z-Score=0.67 → Score 0.5
    # JNJ: 10% Drop bei avg_earnings_move=3%, std=1.5% → Z-Score=4.67 → Score 1.0 (extrem)
    pass

def test_sector_context_bonus():
    """Firmenspezifischer Drop bei stabilem Sektor gibt Overreaction-Punkt."""
    pass

def test_continued_decline_graduated():
    """Milde neue Tiefs (<2% unter Dip-Low) bekommen nur -0.5 statt -1.5."""
    pass

def test_rsi_penalty_uptrend_exemption():
    """RSI 42 bei Aktie über SMA200 bekommt KEINEN Penalty."""
    pass

def test_dynamic_stabilization_timing():
    """15% Drop verlangt 3 Tage Stabilisierung, 8% Drop verlangt 2 Tage."""
    pass
```
