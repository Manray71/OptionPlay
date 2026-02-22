# OptionPlay — Strategiedokument v4.2

**Stand:** 2026-02-21
**Geltungsbereich:** Alle Entwicklungsentscheidungen für OptionPlay bis mindestens 60 abgeschlossene Shadow Trades vorliegen
**Priorität:** Dieses Dokument hat Vorrang vor dem Scoring Rebalancing Plan, der Audit-Roadmap und allen anderen Roadmap-Items

---

## 1. Strategische Diagnose

### Das Problem

OptionPlay liefert keine ausreichende Trade-Frequenz. Der Multi-Scan findet 150 Signale bei 354 Symbolen, aber in der Praxis sind die meisten nicht ausführbar. Die Ursache ist dreischichtig:

**Schicht 1 — Over-Engineered Scoring:** 5 Strategien, VIX-Regime-Erkennung, Walk-Forward-Training, Ensemble-Modelle und umfangreiche Filter erzeugen eine Kaskade, die von 150 Signalen nur 3–4 Daily Picks übrig lässt. Zusätzliche Warnungen ("schwache Komponenten") wirken als implizite Filter.

**Schicht 2 — Kein Feedback-Loop:** Es existieren keine Forward-Performance-Daten. Ohne zu wissen, ob Empfehlungen profitabel sind, ist jede Scoring-Optimierung Blindflug.

**Schicht 3 — Strategie-Markt-Fit (das tiefste Problem):** Die realen Anforderungen für einen ausführbaren Bull-Put-Spread sind:
- Net Credit ≥ $2.00 (nach Kommissionen muss genug übrig bleiben)
- Open Interest ≥ 500 pro Leg (sonst kein Fill zu akzeptablem Preis)
- 60–90 DTE als Standard-Laufzeit

Im aktuellen Marktumfeld (schwacher Tech-Sektor, defensive Rotation) ergibt sich ein strukturelles Mismatch:
- **Tech/Growth:** Hat Options-Liquidität, aber schwache Kursdynamik → Scanner findet keine bullischen Setups
- **Defensive/Value:** Scanner findet Setups, aber Puts haben bei 60–90 DTE oft OI < 500 → nicht ausführbar
- **Ergebnis:** Die Schnittmenge aus "gutes Signal" UND "ausführbar" ist nahe null

### Die zentrale Erkenntnis

Das System hat möglicherweise kein Software-Problem. Wenn der Markt keine Bull-Put-Spreads hergibt, ist "keine Empfehlung" die korrekte Antwort. Das Problem ist, dass wir nicht wissen, ob das stimmt — weil wir keine Daten haben.

### Die strategische Entscheidung

1. **Stopp aller Scoring-Optimierungen** bis Forward-Performance-Daten vorliegen.
2. **Shadow Tracker bauen** um erstmals echte Daten zu sammeln.
3. **Watchlist auf Liquidität optimieren** um das Universum ausführbarer Trades zu maximieren.
4. **Akzeptieren, dass manche Marktphasen weniger Trades produzieren** — und das als Feature betrachten, nicht als Bug.

---

## 2. Datenquellen

| Quelle | Daten | Priorität |
|--------|-------|-----------|
| Tradier | Quotes, Options, Historical | Primär |
| Yahoo Finance | VIX (Fallback), Earnings | Sekundär |
| IBKR (optional) | News, Max Pain, Live VIX | Premium |

---

## 3. Watchlist-Bereinigung (Sofortmaßnahme)

### Problem

358 Symbole in der Watchlist, aber ein Großteil hat nicht die Options-Liquidität, um Bull-Put-Spreads mit Credit ≥ $2.00 und OI ≥ 500 zu füllen. Jeder Scan-Durchlauf verarbeitet Hunderte Symbole, von denen die meisten an der Tradability scheitern.

### Maßnahme: Liquidity-Tier-System

Statt die Watchlist zu kürzen, werden Symbole in Liquiditäts-Tiers eingeteilt:

```yaml
# watchlists.yaml — neues Feld pro Symbol
liquidity_tiers:
  tier_1:  # Immer ausführbar — OI typisch >1000 bei 60-90 DTE Puts
    # Mega-Caps & hochliquide ETFs
    - SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV, XLI, XLP, XLU
    - AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, JPM, BAC, WFC
    - AMD, INTC, NFLX, DIS, PFE, JNJ, UNH, HD, WMT, COST
    # ... ca. 50-60 Symbole

  tier_2:  # Meist ausführbar — OI typisch 100-1000
    # Large-Caps mit gutem Optionsmarkt
    # ... ca. 100 Symbole

  tier_3:  # Eingeschränkt — OI oft <100, nur bei hoher IV handelbar
    # Mid-Caps, defensive Nebenwerte
    # ... Rest
```

### Auswirkung auf Scans

- `daily_picks` scannt primär **Tier 1** (beste Chancen auf ausführbare Trades)
- `scan` und `multi` scannen weiterhin alles, aber das Tier wird im Output angezeigt
- Shadow Tracker loggt das Tier mit — nach 30+ Trades sehen wir, ob Tier-2/3-Empfehlungen überhaupt ausführbar sind

### Erstellen der Tier-Liste

Einmaliger Scan aller 358 Symbole mit Tradier Options-Chain-Abfrage:
- Für jedes Symbol: Prüfe OI der ATM-Puts bei 60–90 DTE
- OI > 500 → Tier 1
- OI 50–500 → Tier 2
- OI < 50 → Tier 3

Als Utility-Script implementieren (`scripts/classify_liquidity.py`), das 1x pro Monat laufen kann.

---

## 4. Phase 1 — Shadow Trade Tracker

### Ziel

Automatische Protokollierung und Nachverfolgung aller System-Empfehlungen, um erstmals echte Forward-Performance-Daten zu generieren. Kein manueller Input. Kein Papertrade.

### Neues Modul

```
~/OptionPlay/src/shadow_tracker.py
~/OptionPlay/data/shadow_trades.db    (SQLite)
```

### Neue MCP-Tools

| Tool | Alias | Beschreibung |
|------|-------|-------------|
| `optionplay_shadow_log` | `shadow_log` | Manueller Log einer Empfehlung (Fallback) |
| `optionplay_shadow_review` | `shadow_review` | Performance-Review aller Shadow Trades |
| `optionplay_shadow_stats` | `shadow_stats` | Aggregierte Statistiken |
| `optionplay_shadow_details` | `shadow_detail` | Detail-View eines einzelnen Shadow Trades |

### Datenbank-Schema

```sql
CREATE TABLE shadow_trades (
    id              TEXT PRIMARY KEY,        -- UUID
    logged_at       TEXT NOT NULL,           -- ISO 8601 Timestamp
    source          TEXT NOT NULL,           -- 'daily_picks' | 'scan' | 'manual'

    -- Signal-Daten (zum Zeitpunkt der Empfehlung)
    symbol          TEXT NOT NULL,
    strategy        TEXT NOT NULL,           -- 'pullback' | 'bounce' | 'ath_breakout' | 'earnings_dip' | 'trend_continuation'
    score           REAL NOT NULL,
    enhanced_score  REAL,
    liquidity_tier  INTEGER,                -- 1, 2, oder 3

    -- Trade-Parameter
    short_strike    REAL NOT NULL,
    long_strike     REAL NOT NULL,
    spread_width    REAL NOT NULL,           -- short_strike - long_strike
    est_credit      REAL NOT NULL,           -- Realistischer Credit (Short Bid - Long Ask)
    expiration      TEXT NOT NULL,           -- YYYY-MM-DD
    dte             INTEGER NOT NULL,

    -- Options-Markt-Daten bei Logging
    short_bid       REAL,
    short_ask       REAL,
    short_oi        INTEGER,
    long_bid        REAL,
    long_ask        REAL,
    long_oi         INTEGER,

    -- Markt-Kontext bei Logging
    price_at_log    REAL NOT NULL,
    vix_at_log      REAL,
    regime_at_log   TEXT,
    stability_at_log REAL,

    -- Outcome-Tracking (wird nachträglich befüllt)
    status          TEXT DEFAULT 'open',     -- 'open' | 'max_profit' | 'partial_profit' | 'stop_loss' | 'max_loss' | 'partial_loss'
    resolved_at     TEXT,
    price_at_expiry REAL,
    price_min       REAL,                    -- Tiefster Kurs während Laufzeit
    price_at_50pct  REAL,
    days_to_50pct   INTEGER,
    theoretical_pnl REAL,
    spread_value_at_resolve REAL,    -- Tatsächlicher Spread-Wert (Short Ask - Long Bid) bei Resolution
    outcome_notes   TEXT
);

CREATE TABLE shadow_rejections (
    id              TEXT PRIMARY KEY,        -- UUID
    logged_at       TEXT NOT NULL,
    source          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    score           REAL NOT NULL,
    liquidity_tier  INTEGER,
    short_strike    REAL,
    long_strike     REAL,
    rejection_reason TEXT NOT NULL,          -- 'low_credit' | 'low_oi' | 'no_bid' | 'wide_spread' | 'no_chain'
    actual_credit   REAL,
    short_oi        INTEGER,
    details         TEXT                     -- JSON
);

CREATE INDEX idx_shadow_symbol ON shadow_trades(symbol);
CREATE INDEX idx_shadow_status ON shadow_trades(status);
CREATE INDEX idx_shadow_strategy ON shadow_trades(strategy);
CREATE INDEX idx_shadow_expiration ON shadow_trades(expiration);
CREATE INDEX idx_shadow_logged ON shadow_trades(logged_at);
CREATE INDEX idx_shadow_tier ON shadow_trades(liquidity_tier);
CREATE INDEX idx_rejected_reason ON shadow_rejections(rejection_reason);
CREATE INDEX idx_rejected_symbol ON shadow_rejections(symbol);
```

### Tradability Gate — Nur ausführbare Trades loggen

Ein Trade wird nur als Shadow Trade geloggt, wenn er in der Praxis ausführbar wäre. Ohne dieses Gate sind die Daten wertlos.

#### Schwellenwerte

```yaml
# settings.yaml
tradability_gate:
  min_net_credit: 2.00
  min_open_interest: 500
  min_bid: 0.10
  max_bid_ask_spread_pct: 30

# strategies.yaml → high_volatility Profil
# price.maximum von 300 auf 1500 anheben (konsistent mit trading_rules.yaml)
```

Das `high_volatility`-Profil (VIX > 30) hatte einen Preis-Cap bei $300 — der einzige Profil-spezifische Preis-Filter. Alle anderen Profile erben `price_max: 1500` aus `trading_rules.yaml`. Der Tradability Gate ersetzt Preis-Obergrenzen als Qualitätsfilter.

#### Implementierung

```python
def check_tradability(symbol, short_strike, long_strike, expiration):
    """
    Prüft ob ein Bull-Put-Spread tatsächlich ausführbar wäre.
    Nutzt Tradier Options-Chain-Daten.
    
    Returns: (tradeable: bool, reason: str, details: dict)
    """
    chain = get_options_chain(symbol, expiration, right='P')
    
    short_put = find_option(chain, short_strike)
    long_put = find_option(chain, long_strike)
    
    if not short_put or not long_put:
        return False, 'no_chain', {}
    
    # 1. Bid muss existieren
    if short_put['bid'] < 0.10:
        return False, 'no_bid', {'short_bid': short_put['bid']}
    
    # 2. Open Interest >= 500 auf beiden Seiten
    if short_put.get('open_interest', 0) < 500:
        return False, 'low_oi', {'short_oi': short_put.get('open_interest', 0)}
    if long_put.get('open_interest', 0) < 500:
        return False, 'low_oi', {'long_oi': long_put.get('open_interest', 0)}
    
    # 3. Bid-Ask-Spread Check
    midpoint = (short_put['bid'] + short_put['ask']) / 2
    if midpoint > 0:
        spread_pct = (short_put['ask'] - short_put['bid']) / midpoint * 100
        if spread_pct > 30:
            return False, 'wide_spread', {'spread_pct': spread_pct}
    
    # 4. Net Credit >= $2.00 (konservativ: Sell at Bid, Buy at Ask)
    net_credit = short_put['bid'] - long_put['ask']
    if net_credit < 2.00:
        return False, 'low_credit', {'net_credit': net_credit}
    
    return True, 'tradeable', {
        'net_credit': net_credit,
        'short_bid': short_put['bid'],
        'short_ask': short_put['ask'],
        'short_oi': short_put.get('open_interest', 0),
        'long_bid': long_put['bid'],
        'long_ask': long_put['ask'],
        'long_oi': long_put.get('open_interest', 0),
    }
```

#### Rejection-Tracking ist genauso wertvoll wie Trade-Tracking

Abgelehnte Trades werden in `shadow_rejections` erfasst. Diese Tabelle beantwortet: **Warum finden wir keine Trades?**

Mögliche Erkenntnisse:
- 80% scheitern an `low_oi` → Watchlist-Problem (zu viele illiquide Symbole)
- 80% scheitern an `low_credit` → Strike-Empfehlungen zu konservativ (zu weit OTM)
- Gleichmäßige Verteilung → Markt gibt generell keine Bull-Put-Spreads her (korrekte Antwort: nicht traden)

### Integration in `daily_picks`

Am Ende von `daily_picks` wird für jeden Pick der Tradability Check durchgeführt. Nur Trades, die bestehen, werden als Shadow Trade geloggt. Abgelehnte landen in `shadow_rejections`.

```python
for pick in daily_picks_results:
    tradeable, reason, details = check_tradability(
        pick['symbol'], pick['short_strike'], pick['long_strike'], pick['expiration']
    )
    
    if tradeable:
        shadow_tracker.log_trade(
            source='daily_picks',
            symbol=pick['symbol'],
            strategy=pick['strategy'],
            score=pick['score'],
            enhanced_score=pick['enhanced_score'],
            short_strike=pick['short_strike'],
            long_strike=pick['long_strike'],
            est_credit=details['net_credit'],   # Realistischer Credit!
            expiration=pick['expiration'],
            price_at_log=pick['current_price'],
            vix_at_log=current_vix,
            regime_at_log=current_regime,
            stability_at_log=pick.get('stability'),
            liquidity_tier=pick.get('liquidity_tier'),
            short_bid=details['short_bid'],
            short_ask=details['short_ask'],
            short_oi=details['short_oi'],
            long_bid=details['long_bid'],
            long_ask=details['long_ask'],
            long_oi=details['long_oi'],
        )
    else:
        shadow_tracker.log_rejection(
            source='daily_picks',
            symbol=pick['symbol'],
            strategy=pick['strategy'],
            score=pick['score'],
            short_strike=pick['short_strike'],
            long_strike=pick['long_strike'],
            rejection_reason=reason,
            actual_credit=details.get('net_credit'),
            short_oi=details.get('short_oi'),
            details=json.dumps(details),
        )
```

**Duplikat-Erkennung:** Über (Datum, Symbol, Short Strike, Long Strike).

**Daily-Picks-Output erweitern:** Tradability-Status im sichtbaren Output anzeigen:

```markdown
## #1 — AAPL | Pullback | Score 10.3
Strikes: Short $240 / Long $230 | Width $10
Credit: $2.45 (Bid $4.20 / Ask $1.75) | OI: 1,240 / 890
✅ TRADEABLE

## #2 — CVS | Pullback | Score 10.4
Strikes: Short $70 / Long $60 | Width $10
Credit: $0.85 | OI: 120 / 45
❌ NOT TRADEABLE (low_oi, low_credit)
```

#### Auto-Logging bei Scans (konfigurierbar)

```yaml
shadow_tracker:
  enabled: true
  auto_log_daily_picks: true
  auto_log_scans: false
  auto_log_min_score: 8.0
```

### Outcome-Resolution-Logik

Die Resolution nutzt **echte Options-Chain-Daten von Tradier**, nicht nur den Aktienkurs. Das PLAYBOOK sieht 50% Profit-Target als Standard-Exit vor — ohne den tatsächlichen Spread-Wert lässt sich nicht bestimmen, ob dieser Exit gegriffen hätte.

```python
def resolve_trade(trade):
    """
    1. Options-Chain holen → aktuellen Spread-Wert berechnen
       current_spread_value = short_put_ask - long_put_bid
    
    2. 50% Profit-Target: spread_value <= est_credit * 0.50 → 'partial_profit'
    3. Stop-Loss: spread_value >= est_credit * 2.50 → 'stop_loss'
    4. Expiration (kursbasiert): max_profit / max_loss / partial_loss
    5. Fallback bei fehlender Chain: kursbasierter Stop-Loss
    6. Sonst → 'open'
    """
```

#### P&L-Berechnung

```python
def calculate_pnl(trade, outcome, spread_value_at_resolve):
    credit = trade.est_credit * 100

    if outcome == 'partial_profit':
        return (trade.est_credit - spread_value_at_resolve) * 100
    elif outcome == 'max_profit':
        return credit
    elif outcome == 'stop_loss':
        return -(spread_value_at_resolve - trade.est_credit) * 100
    elif outcome == 'max_loss':
        return -(trade.spread_width * 100 - credit)
    elif outcome == 'partial_loss':
        intrinsic = max(0, trade.short_strike - price_at_expiry) * 100
        return credit - intrinsic
```

**P&L basiert auf echten Options-Chain-Preisen bei Review. Expiration-Outcomes kursbasiert.**

### MCP-Tool-Spezifikationen

#### `shadow_review`

**Parameter:**
- `resolve` (bool, default: true)
- `status_filter` (string, default: 'all') — 'open' | 'closed' | 'all'
- `strategy_filter` (string, optional)
- `days_back` (int, default: 90)

**Output:**

```markdown
# Shadow Trade Review — 2026-02-21

## Zusammenfassung
- Shadow Trades: 47 geloggt | Rejections: 76 (62% nicht ausführbar)
- Offen: 12 | Geschlossen: 35
- Win-Rate: 71.4% (25/35) | Theo. P&L: +$2,340

## Offene Trades
| Symbol | Tier | Strategie | Score | Short | Long | Credit | Exp | DTE | Kurs | Status |
|--------|------|-----------|-------|-------|------|--------|-----|-----|------|--------|
| AAPL   | 1    | pullback  | 10.3  | $240  | $230 | $2.45  | 04-17 | 55 | $264 | ✅ Safe |

## Kürzlich geschlossen
| Symbol | Strategie | Score | Ergebnis | P&L | Tage |
|--------|-----------|-------|----------|-----|------|
| MSFT   | bounce    | 8.5   | ✅ Max Profit | +$245 | 42 |
```

#### `shadow_stats`

**Parameter:**
- `group_by` (string, default: 'strategy') — 'strategy' | 'score_bucket' | 'regime' | 'month' | 'symbol' | 'tier' | 'rejection_reason'
- `min_trades` (int, default: 5)

**Output:**

```markdown
# Shadow Trade Statistiken

## Nach Strategie
| Strategie | Trades | Win-Rate | Avg P&L | Best | Worst |
|-----------|--------|----------|---------|------|-------|
| pullback  | 22     | 77.3%   | +$168  | +$280 | -$380 |

## Nach Liquidity-Tier
| Tier | Empfehlungen | Tradeable | Rate |
|------|-------------|-----------|------|
| 1    | 45          | 38        | 84%  |
| 2    | 52          | 9         | 17%  |
| 3    | 26          | 0         | 0%   |

## Rejection-Analyse
| Grund       | Anzahl | Anteil |
|-------------|--------|--------|
| low_credit  | 34     | 45%    |
| low_oi      | 23     | 30%    |
| wide_spread | 12     | 16%    |
| no_bid      | 7      | 9%     |
```

#### `shadow_log` — Manueller Fallback
#### `shadow_detail` — Detail-View (Parameter: `trade_id`)

### Implementierungs-Hinweise

- **Tradier-API** für Options-Chain und Historical Data. Existierende Endpunkte nutzen.
- **SQLite WAL-Modus** für parallelen Zugriff.
- **API-Budget:** Tradability Check = 1 Options-Chain-Call pro Kandidat. Bei 10 Daily Picks akzeptabel.

### Implementierungs-Reihenfolge

1. `shadow_tracker.py` mit SQLite-Schema (beide Tabellen) und Basis-CRUD
2. `check_tradability()` mit Tradier Options-Chain
3. Integration in `daily_picks` (Auto-Logging + Rejection-Tracking)
4. `shadow_review` Tool (Outcome-Resolution)
5. `shadow_stats` Tool (inkl. Rejection- und Tier-Analyse)
6. `shadow_log` und `shadow_detail` Tools
7. Tests
8. MCP-Tool-Registrierung in `mcp_server.py`

Optional parallel: `scripts/classify_liquidity.py` für Tier-Klassifizierung.

**Zeitrahmen:** 2–3 Tage fokussierte Implementierung, dann Daten sammeln.

---

## 5. Phase Gates

### Gate 1 → Phase 2 (nach 30 abgeschlossenen Shadow Trades)

| Frage | Wenn ja | Wenn nein |
|-------|---------|-----------|
| Win-Rate > 65%? | Scoring OK, Frequenz ist das Problem | Scoring überarbeiten |
| Score > 9 besser als 5–7? | Score prädiktiv → Schwelle senken | Lean-Modus bauen |
| Tradeable-Rate Tier 1 > 70%? | Watchlist-Fokus auf Tier 1 reicht | Strikes näher an ATM |
| > 50% Rejections wegen low_credit? | Breitere Spreads oder höheres Delta | Andere Gründe adressieren |
| > 50% Rejections wegen low_oi? | Watchlist auf liquide Werte kürzen | OI-Threshold prüfen |

**Mögliche Phase-2-Maßnahmen (erst nach Daten entscheiden):**
- Min-Score senken
- Watchlist auf Tier 1 fokussieren
- Strike-Empfehlungen weniger konservativ (höheres Delta)
- Breitere Spreads ($10–$15) für höheren Credit
- DTE-Range erweitern (45–120 statt 60–90)
- Lean-Modus (3 Binär-Kriterien statt Punkte-Score)

### Gate 2 → Phase 3 (nach 60 Shadow Trades + 2 VIX-Regime)

| Frage | Aktion |
|-------|--------|
| Welche Scoring-Komponenten korrelieren mit Outcomes? | Nur diese behalten |
| VIX-Regime-Anpassungen wertschöpfend? | Wenn nein: statische Parameter |
| Stability-Score liefert Mehrwert? | Wenn nein: entfernen |

---

## 6. Parkplatz — Gesperrte Items

### Bis Gate 1 (30 Shadow Trades)

- Scoring Rebalancing Task 4 + Task 8
- Phase H der Audit-Roadmap
- Neue Strategien oder Scoring-Modelle
- Ensemble-Optimierung
- Threshold-Tuning ohne Datengrundlage

### Bis Gate 2 (60 Shadow Trades + 2 Regime)

- Scoring-Architektur-Änderungen
- Strategien entfernen/hinzufügen
- VIX-Regime-Logik ändern
- Filter-Kaskade überarbeiten

### Dauerhaft erlaubt

- Bugfixes, Stabilität
- Tradier-Integration abschließen
- Dokumentation, SKILL.md
- Shadow Tracker weiterentwickeln
- Watchlist-Pflege (Tier-Klassifizierung)

---

## 7. Was NICHT gebaut werden soll

- Kein UI/Dashboard
- Kein Real-Time-Monitoring
- Keine Options-Preis-Simulation
- Kein Backtesting-Framework
- Keine Alerts/Notifications
- Kein automatisches Threshold-Tuning
- Kein Fork
- Keine neuen Strategien (Bear-Call, Iron Condors) — erst Bull-Put-Spreads validieren

---

## 8. Erfolgskriterien

### Phase 1 erfolgreich wenn:

- Auto-Logging bei jedem `daily_picks`-Aufruf funktioniert
- Tradability Gate filtert korrekt mit realistischen Schwellenwerten
- Rejection-Tabelle zeigt klar die Ablehnungsgründe
- `shadow_review` und `shadow_stats` liefern korrekte Auswertungen
- Nach 2 Wochen: Klares Bild über Tradeable-Rate pro Tier

### Gesamtprojekt erfolgreich wenn:

OptionPlay liefert **2–3 ausführbare Trade-Kandidaten pro Woche** mit **datenvalidierter Win-Rate > 65%** und **Credit ≥ $2.00**. In Marktphasen ohne passende Setups sagt das System klar "Keine Empfehlung" — und das ist ein valides Ergebnis.

---

## 9. Grundregeln

1. **Daten vor Meinung.** Keine Architekturentscheidungen ohne Shadow-Tracker-Daten.
2. **Tradability vor Signal.** Ein perfekter Score nützt nichts, wenn der Trade nicht ausführbar ist.
3. **Einfachheit vor Eleganz.** Jede Komponente muss sich mit Daten rechtfertigen.
4. **Frequenz vor Perfektion.** Lieber mehr gute Trades als wenige perfekte.
5. **"Kein Trade" ist ein valides Ergebnis.** Manche Marktphasen passen nicht zur Strategie.
6. **Forward-Testing vor Backtesting.** Jetzt zählt nur noch Forward-Performance.
7. **Niemals eigenständig Orders ausführen oder Trades ins Portfolio eintragen.** Nur analysieren und empfehlen. Finale Entscheidung und Ausführung liegt bei Lars.
