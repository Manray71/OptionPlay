# OptionPlay Scoring Rebalancing — Implementierungsplan

**Datum:** 2026-02-21  
**Basis:** scoring_analysis.md (Literaturanalyse)  
**Ziel:** Scoring-System ausbalancieren, Cross-Strategy-Vergleichbarkeit herstellen  
**Ausführung:** Schrittweise im Code-Chat, jeder Schritt verifizierbar

---

## Kontext für den Code-Chat

Dieses Dokument beschreibt 8 Schritte zur Rebalancierung des OptionPlay Scoring-Systems. Jeder Schritt ist eigenständig ausführbar und hat ein klar definiertes Ergebnis. Die Analyse basiert auf einem Literaturvergleich (siehe scoring_analysis.md) und identifiziert folgende Kernprobleme:

1. **Doku-Code-Drift:** YAML max_possible-Werte weichen von der Scoring-Doku ab
2. **Pullback-Kompression:** 14 Komponenten → Raw Max 27.0 → normalisiert selten > 6.0
3. **Event-vs-State-Imbalance:** Trend Continuation dominiert in ruhigen Märkten
4. **Stability Triple-Counting:** 30% Ranking-Gewicht + Post-Filter + Analyzer-DQ
5. **Enhanced Scoring additiv:** +5.5 absolute Punkte verzerren die Skala
6. **VIX-Regime-Inkonsistenz:** Jede Strategie reagiert anders auf VIX

Relevante Dateien:
- `src/analyzers/score_normalization.py` — Normalisierung
- `src/analyzers/feature_scoring_mixin.py` — ML-trained Features
- `src/services/recommendation_engine.py` — Ranking + Daily Picks
- `src/services/enhanced_scoring.py` — Enhanced Scoring Bonuses
- `src/scanner/multi_strategy_scanner.py` — Scanner + Overlap
- `src/scanner/multi_strategy_ranker.py` — Ranker
- `src/analyzers/pullback.py` + `pullback_scoring.py` — Pullback
- `src/analyzers/bounce.py` — Bounce
- `src/analyzers/ath_breakout.py` — ATH Breakout
- `src/analyzers/earnings_dip.py` — Earnings Dip
- `src/analyzers/trend_continuation.py` — Trend Continuation
- `config/scoring_weights.yaml` — YAML-Weights
- `config/enhanced_scoring.yaml` — Enhanced Scoring Config
- `docs/SCORING_SYSTEM.md` — Scoring-Dokumentation

---

## Schritt 1: Diagnostik — Doku-Code-Alignment verifizieren

**Ziel:** Herausfinden, welche max_possible-Werte tatsächlich für die Normalisierung verwendet werden und ob die dokumentierten Werte stimmen.

**Aufgaben:**

1.1 Öffne `src/analyzers/score_normalization.py` und zeige den vollständigen Code. Identifiziere:
   - Wo wird `max_possible` definiert oder geladen?
   - Wird der Wert aus YAML gelesen, hardcoded oder dynamisch berechnet?
   - Wie lautet die exakte Normalisierungsformel pro Strategie?

1.2 Öffne `config/scoring_weights.yaml` und zeige die `max_possible`-Werte aller 5 Strategien.

1.3 Prüfe in jedem Analyzer (`pullback.py`, `bounce.py`, `ath_breakout.py`, `earnings_dip.py`, `trend_continuation.py`), ob dort ein eigener `max_possible` gesetzt wird, der den YAML-Wert überschreibt.

1.4 Prüfe `src/analyzers/feature_scoring_mixin.py` — wie interagiert das Mixin mit der Normalisierung? Werden die Mixin-Scores VOR oder NACH der Normalisierung addiert?

1.5 Erstelle eine Vergleichstabelle:

```
| Strategie       | Doku Raw Max | YAML max_possible | Code-Wert (tatsächlich) | Normalisierungsmethode |
|-----------------|-------------|-------------------|------------------------|----------------------|
| Pullback        | 27.0        | 27.65             | ???                    | ???                  |
| Bounce          | 10.0        | 28.57             | ???                    | ???                  |
| ATH Breakout    | 10.0        | 23.0              | ???                    | ???                  |
| Earnings Dip    | 9.5         | 21.0              | ???                    | ???                  |
| Trend Cont.     | 10.5        | 8.70 (sum weights)| ???                    | ???                  |
```

**Erwartetes Ergebnis:** Klares Bild, welche Normalisierung tatsächlich läuft. Daraus ergibt sich, ob die Probleme real oder nur Doku-Fehler sind.

**Erfolgskriterium:** Tabelle vollständig ausgefüllt, Diskrepanzen identifiziert.

---

## Schritt 2: Empirische Score-Verteilungen messen

**Ziel:** Tatsächliche Score-Verteilungen aus der Datenbank extrahieren, um die theoretische Analyse zu validieren.

**Aufgaben:**

2.1 Query gegen `outcomes.db` → `trade_outcomes`-Tabelle:

```sql
SELECT 
    strategy,
    COUNT(*) as n,
    ROUND(AVG(score), 2) as avg_score,
    ROUND(MIN(score), 2) as min_score,
    ROUND(MAX(score), 2) as max_score,
    ROUND(AVG(score) - 1.0 * STDEV(score), 2) as p16,  -- ~16. Percentil
    ROUND(AVG(score) + 1.0 * STDEV(score), 2) as p84,  -- ~84. Percentil
    SUM(CASE WHEN score >= 5.0 THEN 1 ELSE 0 END) as moderate_plus,
    SUM(CASE WHEN score >= 7.0 THEN 1 ELSE 0 END) as strong,
    SUM(CASE WHEN score >= 8.0 THEN 1 ELSE 0 END) as excellent
FROM trade_outcomes
GROUP BY strategy
ORDER BY strategy;
```

2.2 Falls SQLite kein STDEV hat, berechne die Percentile explizit:

```sql
-- Percentile pro Strategie (P10, P25, P50, P75, P90, P95)
-- Für jede Strategie separat:
SELECT strategy, score
FROM trade_outcomes
WHERE strategy = 'pullback'
ORDER BY score;
-- Dann programmatisch Percentile berechnen
```

2.3 Erstelle ein Python-Script, das die Verteilungen visualisiert (optional, aber hilfreich):

```python
# Script: scripts/analyze_score_distributions.py
# Liest trade_outcomes, plottet Histogramme aller 5 Strategien übereinander
# Zeigt Percentile-Marks
# Speichert als PNG in reports/
```

2.4 Berechne den "P95 effective max" pro Strategie — das wird für Schritt 4 benötigt.

**Erwartetes Ergebnis:** Empirische Bestätigung oder Widerlegung der theoretischen Kompression. Pullback sollte niedrigeren Median und schmalere Verteilung zeigen als Bounce/ATH.

**Erfolgskriterium:** Percentile-Tabelle aller 5 Strategien + P95-Werte.

---

## Schritt 3: Event-Priority-System implementieren

**Ziel:** Verhindern, dass Trend Continuation in ruhigen Märkten das gesamte Ranking dominiert. Schnellster Fix mit höchstem Impact.

**Aufgaben:**

3.1 In `config/scoring_weights.yaml` eine neue Sektion ergänzen:

```yaml
strategy_balance:
  # Event-Bonus: seltene, zeitkritische Signale werden priorisiert
  signal_type_bonus:
    pullback: 0.5
    bounce: 0.5
    ath_breakout: 0.5
    earnings_dip: 0.5
    trend_continuation: 0.0
  
  # Capacity Limits: max Signale pro Strategie in daily_picks
  strategy_caps:
    trend_continuation: 3    # Max 3 von 5 Picks dürfen TC sein
    default: 5               # Andere Strategien: kein Cap
  
  # Diversity: Mindestens N verschiedene Strategien in Top-5
  min_strategies_in_picks: 2
```

3.2 In `src/services/recommendation_engine.py` den Event-Bonus anwenden:

- Finde die Stelle, wo `combined_score` berechnet wird (aktuell: `0.7 × signal + 0.3 × stability`)
- Addiere `signal_type_bonus` NACH der Normalisierung, VOR dem Ranking
- Der Bonus wird aus der YAML-Config gelesen

```python
# Pseudo-Code:
event_bonus = self.config.get('strategy_balance', {}).get('signal_type_bonus', {})
for candidate in candidates:
    bonus = event_bonus.get(candidate.strategy, 0.0)
    candidate.combined_score += bonus
```

3.3 In `src/scanner/multi_strategy_scanner.py` oder `recommendation_engine.py` das Capacity Limit implementieren:

- Nach dem Ranking, vor dem finalen Output
- Zähle Signale pro Strategie
- Wenn ein Strategy-Cap erreicht ist, überspringe weitere Signale dieser Strategie
- Diversity-Check: Falls Top-N nur eine Strategie enthält, ersetze den schwächsten durch den besten Kandidaten einer anderen Strategie

3.4 Test: Laufe `daily_picks()` einmal mit und einmal ohne die Änderungen. Vergleiche die Ergebnisse:

```python
# Vorher/Nachher-Vergleich:
# - Wie viele TC-Signale in Top-5 vorher vs. nachher?
# - Welche Event-Signale rutschen durch den Bonus nach oben?
```

**Erwartetes Ergebnis:** Diversere Daily Picks. In bullischen Märkten nicht mehr 4/5 Trend Continuation.

**Erfolgskriterium:** Daily Picks zeigen mindestens 2 verschiedene Strategien. TC maximal 3 von 5.

---

## Schritt 4: Normalisierung auf Percentile-Rank umstellen

**Ziel:** Strategien verteilungsunabhängig vergleichbar machen.

**Aufgaben:**

4.1 Erstelle eine neue Klasse `PercentileNormalizer` in `src/analyzers/score_normalization.py`:

```python
class PercentileNormalizer:
    """Normalisiert Scores auf Basis historischer Verteilungen.
    
    Statt raw/max × 10 wird der Percentile-Rank berechnet:
    Ein Score, der besser ist als 80% aller historischen Scores
    der gleichen Strategie, wird zu 8.0 normalisiert.
    """
    
    def __init__(self):
        self.percentile_tables: dict[str, np.ndarray] = {}
        self._load_historical_percentiles()
    
    def _load_historical_percentiles(self):
        """Lädt Percentile-Tabellen aus trade_outcomes.
        
        Erstellt 101 Percentile (0-100) pro Strategie.
        Fallback auf lineare Normalisierung wenn < 100 Samples.
        """
        # DB-Query: SELECT strategy, score FROM trade_outcomes
        # np.percentile(scores, range(0, 101)) pro Strategie
        pass
    
    def normalize(self, raw_score: float, strategy: str) -> float:
        """Score → Percentile-Rank (0.0 – 10.0)"""
        if strategy not in self.percentile_tables:
            return self._fallback_normalize(raw_score, strategy)
        
        table = self.percentile_tables[strategy]
        rank = np.searchsorted(table, raw_score, side='right')
        return min(rank / 10.0, 10.0)
    
    def _fallback_normalize(self, raw_score, strategy):
        """Fallback: Aktuelle Methode (raw/max × 10)"""
        # Bestehende Logik beibehalten
        pass
```

4.2 Integriere `PercentileNormalizer` in den bestehenden Normalisierungsflow:

- Prüfe, wie die aktuelle Normalisierung aufgerufen wird (vermutlich eine Funktion `normalize_score(raw, strategy)` oder Methode auf dem Analyzer)
- Ersetze den Aufruf durch den neuen Normalizer
- Behalte die alte Methode als Fallback (< 100 Samples)

4.3 Erstelle ein Kalibrierungs-Script:

```python
# scripts/calibrate_percentile_normalization.py
#
# 1. Liest alle Scores aus trade_outcomes
# 2. Berechnet Percentile-Tabellen pro Strategie
# 3. Speichert als JSON: ~/.optionplay/models/percentile_tables.json
# 4. Validiert: Gleicher Percentile-Rank → gleiche historische Qualität
#
# Output:
# Pullback  P50: 4.8 → Normalized 5.0  ✓
# Bounce    P50: 5.5 → Normalized 5.0  ✓
# ATH       P50: 5.8 → Normalized 5.0  ✓
# ...
```

4.4 **Alternativ-Option (falls Percentile-Rank zu aufwendig):** P95-Dynamic-Max als schnelleren Fix implementieren:

```python
# Schneller Fix: Statt theoretischem Max das P95 verwenden
effective_max = {
    'pullback': P95_from_step2,      # vermutlich ~18-20 statt 27
    'bounce': P95_from_step2,        # vermutlich ~8.5
    'ath_breakout': P95_from_step2,  # vermutlich ~8.0
    'earnings_dip': P95_from_step2,  # vermutlich ~7.5
    'trend_continuation': P95_from_step2,  # vermutlich ~8.0
}
# Dann: normalized = (raw / effective_max) × 10, capped at 10.0
```

4.5 Test: Laufe einen Multi-Strategy-Scan mit alter und neuer Normalisierung. Vergleiche:
- Verteilen sich die normalisierten Scores jetzt gleichmäßiger über Strategien?
- Produziert Pullback jetzt mehr STRONG-Signale?
- Bleiben die Rankings innerhalb einer Strategie konsistent?

**Erwartetes Ergebnis:** Ähnliche Mediane (~5.0) über alle Strategien bei ähnlicher Signal-Qualität.

**Erfolgskriterium:** Median-Abweichung zwischen Strategien < 1.0 Punkt (vorher vermutlich 2-3 Punkte).

---

## Schritt 5: Stability-Gewichtung von 30% auf 15% senken

**Ziel:** Triple-Counting reduzieren. Signal-Qualität soll stärker durchschlagen.

**Aufgaben:**

5.1 In `src/services/recommendation_engine.py` die Ranking-Formel ändern:

```python
# VORHER:
base_score = 0.7 * signal_score + 0.3 * (stability_score / 10)

# NACHHER:
base_score = 0.85 * signal_score + 0.15 * (stability_score / 10)
```

5.2 Falls die Gewichte in `config/scoring_weights.yaml` konfigurierbar sind, dort ändern:

```yaml
ranking:
  signal_weight: 0.85      # vorher: 0.70
  stability_weight: 0.15   # vorher: 0.30
```

5.3 Post-Filter vereinfachen — in `src/scanner/multi_strategy_scanner.py`:

```python
# VORHER: 4 Tiers
# Premium (≥80): min 2.5
# Good (≥70): min 3.5
# Acceptable (≥65): min 4.0
# OK (≥50): min 5.0

# NACHHER: 2 Tiers
# Qualified (≥60): min 3.5    (Standard)
# Blacklist (<60): rejected    (Keine Signale)
```

Hinweis: Der Analyzer-Level DQ (TC<70, ED<60) bleibt als harter Gate erhalten. Die Vereinfachung betrifft nur den Post-Filter.

5.4 Test: Vergleiche daily_picks vorher/nachher:
- Erscheinen jetzt Symbole mit Stability 65-75, die vorher gefiltert wurden?
- Verschwinden High-Stability/Low-Signal-Symbole aus den Top-5?

**Erwartetes Ergebnis:** Signal-Qualität dominiert das Ranking stärker. Symbole mit mittlerer Stability aber starkem Signal rücken auf.

**Erfolgskriterium:** Ranking-Veränderungen nachvollziehbar. Kein Absturz der Backtest-Performance.

---

## Schritt 6: Enhanced Scoring auf multiplikativen Ansatz umstellen

**Ziel:** Die additive +5.5-Verzerrung eliminieren.

**Aufgaben:**

6.1 In `src/services/enhanced_scoring.py` die Formel umstellen:

```python
# VORHER (additiv):
enhanced_score = signal_score + liquidity_bonus + credit_bonus + pullback_bonus + stability_bonus
# Range: 0 – 15.5

# NACHHER (multiplikativ):
bonus_factor = 1.0

# Liquidity (max +0.10)
if open_interest >= 5000:
    bonus_factor += 0.10
elif open_interest >= 700:
    bonus_factor += 0.07
elif open_interest >= 100:
    bonus_factor += 0.03
# < 100: rejected (unverändert)

# Credit Quality (max +0.08)
if credit_return >= 0.10:
    bonus_factor += 0.08
elif credit_return >= 0.07:
    bonus_factor += 0.05
elif credit_return >= 0.04:
    bonus_factor += 0.02

# Pullback Position (max +0.05)
if above_sma20 and above_sma200:
    bonus_factor += 0.05
elif above_sma200:
    bonus_factor += 0.025

# Stability Bonus (max +0.05)
if stability >= 85:
    bonus_factor += 0.05
elif stability >= 75:
    bonus_factor += 0.025

enhanced_score = signal_score * bonus_factor
# Range: signal × 1.00 bis signal × 1.28
```

6.2 In `config/enhanced_scoring.yaml` die neuen Faktoren konfigurierbar machen:

```yaml
enhanced_scoring:
  mode: multiplicative    # NEU: 'additive' (alt) oder 'multiplicative' (neu)
  
  multiplicative_bonuses:
    liquidity:
      high: 0.10      # OI >= 5000
      medium: 0.07     # OI >= 700
      low: 0.03        # OI >= 100
    credit:
      excellent: 0.08  # >= 10%
      good: 0.05       # >= 7%
      adequate: 0.02   # >= 4%
    position:
      strong: 0.05     # Above SMA20 + SMA200
      moderate: 0.025  # Above SMA200 only
    stability:
      premium: 0.05    # >= 85
      good: 0.025      # >= 75
```

6.3 Test: Den `mode`-Switch nutzen, um additiv vs. multiplikativ zu vergleichen:
- Wie stark ändert sich das Ranking?
- Werden schwache Signale (< 4.0) mit hohen Bonuses jetzt korrekt niedriger gerankt?

**Erwartetes Ergebnis:** Relative Ranking-Ordnung bleibt ähnlich, aber die Skala ist konsistenter (0–12.8 statt 0–15.5).

**Erfolgskriterium:** Kein Signal unter 4.0 schafft es durch Enhanced Scoring in die Top-5.

---

## Schritt 7: VIX-Regime harmonisieren

**Ziel:** Einheitliche VIX-Behandlung über alle Strategien.

**Aufgaben:**

7.1 In `config/scoring_weights.yaml` eine globale VIX-Sektion definieren:

```yaml
vix_regime:
  # Globale Multiplikatoren (alle Strategien)
  global_multipliers:
    low: 1.00
    normal: 1.00
    elevated: 0.90
    danger: 0.75
    high: 0.00          # Kein Trading — Playbook §3
  
  # Strategie-spezifische Overlays (multipliziert mit global)
  strategy_overlays:
    ath_breakout:
      elevated: 0.85    # Effektiv: 0.90 × 0.85 = 0.765
      danger: 0.60      # Effektiv: 0.75 × 0.60 = 0.45
    trend_continuation:
      elevated: 0.90    # Effektiv: 0.90 × 0.90 = 0.81
      danger: 0.70      # Effektiv: 0.75 × 0.70 = 0.525
    earnings_dip:
      elevated: 1.05    # Effektiv: 0.90 × 1.05 = 0.945 (Dips profitieren von IV)
```

7.2 In `src/analyzers/score_normalization.py` oder einer neuen Utility `vix_adjustment.py`:

```python
def apply_vix_regime(score: float, strategy: str, vix_regime: str, config: dict) -> float:
    """Wendet globale + strategie-spezifische VIX-Multiplikatoren an."""
    global_mult = config['vix_regime']['global_multipliers'].get(vix_regime, 1.0)
    overlay = config['vix_regime'].get('strategy_overlays', {}).get(strategy, {})
    strategy_mult = overlay.get(vix_regime, 1.0)
    return score * global_mult * strategy_mult
```

7.3 Entferne die individuellen VIX-Behandlungen aus den einzelnen Analyzern:

- `trend_continuation.py`: Entferne den 0.0× Multiplikator bei HIGH (wird jetzt global gehandhabt)
- `ath_breakout.py`: Entferne `enabled: false` bei HIGH (wird jetzt durch 0.0× global abgedeckt)
- Behalte die Stability-Threshold-Anpassungen in den Analyzern (das ist ein separater Mechanismus)

7.4 In `src/scanner/multi_strategy_scanner.py`: Bei VIX HIGH den Scanner komplett stoppen (nicht nur Scores auf 0 setzen):

```python
if vix_regime == 'high':
    return ScanResult(
        candidates=[],
        message="VIX > 30 — keine neuen Trades (PLAYBOOK §3)",
        vix_regime='high'
    )
```

7.5 Test:
- Simuliere VIX-Regime-Wechsel (setze VIX manuell auf 12, 18, 22, 27, 32)
- Prüfe, dass alle Strategien konsistent reagieren
- Prüfe, dass bei VIX > 30 der Scanner keine Signale produziert

**Erwartetes Ergebnis:** Einheitliches, vorhersagbares VIX-Verhalten. Keine Strategie wird willkürlich deaktiviert.

**Erfolgskriterium:** VIX-Multiplikatoren wirken konsistent. Playbook §3 wird sauber durchgesetzt.

---

## Schritt 8: Dokumentation aktualisieren + Backtest-Validierung

**Ziel:** SCORING_SYSTEM.md aktualisieren und sicherstellen, dass die Änderungen die Performance nicht verschlechtern.

**Aufgaben:**

8.1 Backtest-Validierung aller Änderungen:

```python
# scripts/validate_scoring_changes.py
#
# 1. Lade historische Signale aus trade_outcomes
# 2. Berechne normalized_scores mit ALTER Methode
# 3. Berechne normalized_scores mit NEUER Methode
# 4. Vergleiche:
#    - Win Rate pro Strategie: bleibt gleich oder besser?
#    - Ranking-Korrelation: Sind die "guten" Trades immer noch oben?
#    - Score-Verteilung: Sind die Mediane jetzt ähnlicher?
#
# Output: Comparison Report mit vorher/nachher
```

8.2 Spezifisch prüfen:
- Pullback Win Rate bei STRONG-Signalen (>= 7.0): Vorher vs. nachher
- Wie viele Pullback-Signale erreichen jetzt STRONG? (Sollte deutlich mehr sein)
- Trend Continuation: Wird die Performance durch den Event-Bonus oder Cap verschlechtert?
- Enhanced Scoring: Ändert sich die Top-5-Zusammensetzung signifikant?

8.3 `docs/SCORING_SYSTEM.md` aktualisieren:
- Sektion 7: Neue Normalisierungsmethode dokumentieren
- Sektion 8: Neue Ranking-Formel (0.85/0.15)
- Sektion 10: Enhanced Scoring multiplikativ
- Sektion 11: Event-Priority-System dokumentieren
- Sektion 12: Erledigte Tasks markieren

8.4 Version-Bump auf 4.1.0 in allen relevanten Dateien.

**Erwartetes Ergebnis:** Dokumentation und Code sind synchron. Backtest zeigt keine Performance-Regression.

**Erfolgskriterium:** OOS Win Rate aller Strategien bleibt im Bereich ±2% der aktuellen Werte.

---

## Zusammenfassung: Reihenfolge & Zeitschätzung

| Schritt | Was | Aufwand | Abhängigkeit |
|---------|-----|---------|-------------|
| **1** | Diagnostik: Doku-Code-Alignment | 30–60 min | Keine |
| **2** | Empirische Score-Verteilungen | 30–60 min | Keine |
| **3** | Event-Priority-System | 2–3 h | Keine |
| **4** | Percentile-Normalisierung | 3–4 h | Schritt 2 |
| **5** | Stability 30% → 15% | 30–60 min | Keine |
| **6** | Enhanced Scoring multiplikativ | 1–2 h | Schritt 4 |
| **7** | VIX-Harmonisierung | 2–3 h | Keine |
| **8** | Doku + Backtest-Validierung | 2–3 h | Alle vorherigen |
| | **Gesamt** | **~12–16 h** | |

**Empfehlung:** Schritte 1–2 zusammen in einer Session (Diagnostik). Dann 3 + 5 als Quick Wins. Dann 4 + 6 als Kern-Refaktor. Dann 7. Abschluss mit 8.

---

## Hinweise für die Code-Ausführung

- **Keine Orders ausführen oder Trades eintragen** — nur analysieren und Code ändern
- **Git-Branch erstellen** vor Beginn: `git checkout -b feature/scoring-rebalance`
- **Jeden Schritt committen** mit aussagekräftiger Message
- **Tests laufen lassen** nach jedem Schritt: `pytest tests/ -x --tb=short`
- **Bei Schritt 4** (Percentile-Normalisierung): Beide Methoden parallel lauffähig halten, bis Backtest-Validierung in Schritt 8 abgeschlossen ist
- Falls die Diagnostik in Schritt 1 zeigt, dass die Normalisierung bereits YAML max_possible nutzt (und die Doku-Werte nur die Basis-Komponenten beschreiben), dann ist das Kompressionsprobelm möglicherweise kleiner als angenommen — die Analyse in Schritt 2 wird das klären
