# OptionPlay Strategy Training Report

**Generated:** 2026-01-27
**Training Period:** 2022-01 to 2026-01
**Methodology:** Walk-Forward Cross-Validation with VIX Regime Analysis

---

## Executive Summary

Alle vier Trading-Strategien wurden mit Walk-Forward Validation trainiert und auf ihre Performance in verschiedenen VIX-Regimes analysiert.

### Key Findings

| Strategy | OOS Win Rate | Best Regime | Empfehlung |
|----------|--------------|-------------|------------|
| **Bounce** | 65.5% | High VIX (68.5%) | Aktivieren bei VIX > 20 |
| **Pullback** | 64.3% | High VIX (66.3%) | Aktivieren bei VIX > 20 |
| **ATH Breakout** | 83.6% | Low VIX | Aktivieren bei VIX < 20 |
| **Earnings Dip** | 44.8% | High VIX (64.4%) | Mit Vorsicht, nur High VIX |

---

## Strategie-Details

### 1. Pullback Strategy

**Beschreibung:** RSI-Pullback zu Support im Aufwärtstrend

**Performance nach VIX-Regime:**
- **Normal (VIX 15-20):** 50.0% Win Rate, 40 Trades
- **Elevated (VIX 20-30):** 46.7% Win Rate, 467 Trades
- **High (VIX >30):** 66.3% Win Rate, 169 Trades ✓

**Empfehlung:**
- Erhöhung des Min-Scores auf 6.0 (von 5.0)
- Strategie bei VIX > 30 bevorzugen
- Bei normalem VIX vorsichtig sein

---

### 2. Bounce Strategy

**Beschreibung:** Preis-Bounce von etabliertem Support

**Performance nach VIX-Regime:**
- **Normal (VIX 15-20):** 40.0% Win Rate, 30 Trades
- **Elevated (VIX 20-30):** 49.8% Win Rate, 492 Trades
- **High (VIX >30):** 68.5% Win Rate, 130 Trades ✓

**Empfehlung:**
- Erhöhung des Min-Scores auf 6.0
- Beste Performance bei High VIX
- In normalem Umfeld vermeiden

---

### 3. ATH Breakout Strategy

**Beschreibung:** All-Time High Breakout mit Volumen-Bestätigung

**Performance:**
- **OOS Win Rate:** 83.6% (433 Trades)
- Negative Degradation (-9.4%) zeigt gute Generalisierung

**Empfehlung:**
- Erhöhung des Min-Scores auf 7.0
- Bei niedrigem VIX (<20) bevorzugen
- Bei hohem VIX deaktivieren (Breakouts scheitern oft)

---

### 4. Earnings Dip Strategy

**Beschreibung:** Post-Earnings Dip Recovery

**Performance nach VIX-Regime:**
- **Normal (VIX 15-20):** 0.0% Win Rate, 4 Trades (zu wenig Daten)
- **Elevated (VIX 20-30):** 55.2% Win Rate, 395 Trades
- **High (VIX >30):** 64.4% Win Rate, 160 Trades ✓

**Empfehlung:**
- Erhöhung des Min-Scores auf 7.0
- Nur bei erhöhtem/hohem VIX nutzen
- Strikte Earnings-Prüfung beibehalten

---

## Regime-basierte Trading-Regeln

### Low VIX (<15) - Bullisher Markt
- **Bevorzugte Strategien:** ATH Breakout
- **Score-Anpassung:** +1.0 für ATH Breakout
- **Positionsgröße:** Normal (2%)

### Normal VIX (15-20)
- **Bevorzugte Strategien:** ATH Breakout, Bounce
- **Score-Anpassung:** Standard
- **Positionsgröße:** Normal (2%)

### Elevated VIX (20-30) - Erhöhte Volatilität
- **Bevorzugte Strategien:** Pullback, Bounce
- **Score-Anpassung:** +1.0 für Pullback/Bounce
- **Positionsgröße:** Reduziert (1.5%)

### High VIX (>30) - Hohe Volatilität
- **Bevorzugte Strategien:** Bounce, Pullback
- **Score-Anpassung:** Nur höchste Scores (>7)
- **Positionsgröße:** Minimal (1%)
- **ATH Breakout:** Deaktiviert

---

## Technische Details

### Walk-Forward Validation
- **Train-Perioden:** 12 Monate
- **Test-Perioden:** 3 Monate
- **Step:** 3 Monate
- **Epochen:** 4-12 je nach Datenverfügbarkeit

### Degradation-Analyse
| Strategy | In-Sample | Out-of-Sample | Degradation |
|----------|-----------|---------------|-------------|
| Pullback | 74.4% | 64.3% | -10.1% |
| Bounce | 78.2% | 65.5% | -12.7% |
| ATH Breakout | 74.2% | 83.6% | +9.4% |
| Earnings Dip | 66.8% | 44.8% | -22.0% |

**Hinweis:** Negative Degradation bei ATH Breakout ist ein positives Zeichen für robuste Generalisierung.

---

## Exportierte Modelle

Die trainierten Modelle wurden in folgenden Dateien gespeichert:

```
~/.optionplay/models/
├── trained_models.json        # Regime-Performance & Adjustments
├── component_weights.json     # Komponenten-Gewichte
├── production_weights.json    # Produktions-Export
└── production_config.json     # Konsolidierte Konfiguration
```

---

## Nächste Schritte

1. **Integration in MCP-Server:**
   - Regime-Adjustments in Scanner einbauen
   - Dynamische Min-Scores basierend auf VIX

2. **Monitoring:**
   - Live-Performance vs. Backtest vergleichen
   - Weekly Regime-Updates

3. **Erweiterungen:**
   - Per-Symbol Performance-Tracking
   - Sektor-basierte Anpassungen

---

*Report generiert mit OptionPlay Backtesting Framework*
