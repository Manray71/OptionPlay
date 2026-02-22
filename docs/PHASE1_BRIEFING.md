# Phase 1 Briefing — Shadow Trade Tracker

**Für:** Claude Code
**Projekt:** ~/OptionPlay
**Kontext:** Lies `OPTIONPLAY_STRATEGIE_v4.2.md` für die strategische Begründung. Dieses Dokument enthält nur die Implementierungsanweisungen.
**Priorität:** Dieses Feature hat Vorrang vor ALLEN anderen Roadmap-Items. Scoring Rebalancing Task 4, Task 8, Phase H der Audit-Roadmap — alles ist auf Hold.

---

## Auftrag

Baue einen Shadow Trade Tracker, der Empfehlungen von `daily_picks` automatisch protokolliert und deren Ausgang nachverfolgt. Nur Trades, die einen Tradability-Check gegen die echte Options-Chain bestehen, werden geloggt. Abgelehnte Kandidaten werden separat erfasst.

Das System hat aktuell keinen Feedback-Loop. Wir wissen nicht, ob unsere Empfehlungen profitabel sind. Der Shadow Tracker schließt diese Lücke.

---

## Datenquelle

**Tradier** ist die primäre API für Quotes, Options-Chain und Historical Data. Nicht Marketdata.app (veraltet). Nutze die bestehenden Tradier-Endpunkte im Projekt.

---

## Liefergegenstände

### 1. Neues Modul: `src/shadow_tracker.py`

Enthält alle Funktionen für Shadow Trade Management. Keine Abhängigkeiten außer SQLite3, den bestehenden Tradier-API-Funktionen und der Standard-Bibliothek.

### 2. Datenbank: `data/shadow_trades.db` (SQLite, WAL-Modus)

Zwei Tabellen:

```sql
CREATE TABLE shadow_trades (
    id              TEXT PRIMARY KEY,        -- UUID4
    logged_at       TEXT NOT NULL,           -- ISO 8601
    source          TEXT NOT NULL,           -- 'daily_picks' | 'scan' | 'manual'

    symbol          TEXT NOT NULL,
    strategy        TEXT NOT NULL,           -- 'pullback' | 'bounce' | 'ath_breakout' | 'earnings_dip' | 'trend_continuation'
    score           REAL NOT NULL,
    enhanced_score  REAL,
    liquidity_tier  INTEGER,                -- 1, 2, 3

    short_strike    REAL NOT NULL,
    long_strike     REAL NOT NULL,
    spread_width    REAL NOT NULL,
    est_credit      REAL NOT NULL,           -- Realistisch: Short Bid - Long Ask
    expiration      TEXT NOT NULL,           -- YYYY-MM-DD
    dte             INTEGER NOT NULL,

    short_bid       REAL,
    short_ask       REAL,
    short_oi        INTEGER,
    long_bid        REAL,
    long_ask        REAL,
    long_oi         INTEGER,

    price_at_log    REAL NOT NULL,
    vix_at_log      REAL,
    regime_at_log   TEXT,
    stability_at_log REAL,

    status          TEXT DEFAULT 'open',     -- 'open' | 'max_profit' | 'partial_profit' | 'stop_loss' | 'max_loss' | 'partial_loss'
    resolved_at     TEXT,
    price_at_expiry REAL,
    price_min       REAL,
    price_at_50pct  REAL,
    days_to_50pct   INTEGER,
    theoretical_pnl REAL,
    spread_value_at_resolve REAL,    -- Tatsächlicher Spread-Wert (Short Ask - Long Bid) bei Resolution
    outcome_notes   TEXT
);

CREATE TABLE shadow_rejections (
    id              TEXT PRIMARY KEY,
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

DB wird beim ersten Zugriff automatisch erstellt falls nicht vorhanden.

### 3. Tradability Gate: `check_tradability()`

Diese Funktion ist der Kern der Datenqualität. Sie prüft die echte Options-Chain über Tradier bevor ein Shadow Trade geloggt wird.

**Schwellenwerte** (in `config/settings.yaml` unter `tradability_gate`):

```yaml
tradability_gate:
  min_net_credit: 2.00          # USD, berechnet als Short Bid - Long Ask
  min_open_interest: 500        # Pro Leg
  min_bid: 0.10                 # Short Put Bid muss > $0.10 sein
  max_bid_ask_spread_pct: 30    # Prozent des Midpoint
```

**Preis-Filter korrigieren** (in `config/strategies.yaml`):

Das `high_volatility`-Profil (VIX > 30) hat einen Preis-Cap bei $300, der hochpreisige Mega-Caps ausschließt. Dieser muss auf `1500` angehoben werden (konsistent mit `trading_rules.yaml`):

```yaml
# strategies.yaml → profiles → high_volatility → filters → price
price:
  minimum: 50
  maximum: 1500    # war: 300
```

Die anderen Profile (conservative, standard, aggressive) haben keinen eigenen Preis-Filter und erben `price_max: 1500` aus `trading_rules.yaml` — das passt bereits.

**Logik:**

```
1. Options-Chain von Tradier holen (Symbol, Expiration, right='P')
2. Short Put und Long Put anhand der Strikes finden
3. Prüfungen in dieser Reihenfolge (First Fail):
   a. Strikes in Chain vorhanden?          → 'no_chain'
   b. Short Put Bid >= $0.10?              → 'no_bid'
   c. Short Put OI >= 500?                 → 'low_oi'
   d. Long Put OI >= 500?                  → 'low_oi'
   e. Bid-Ask-Spread <= 30% des Midpoint?  → 'wide_spread'
   f. Net Credit (Short Bid - Long Ask) >= $2.00?  → 'low_credit'
4. Alle bestanden → return (True, 'tradeable', details_dict)
5. Fehlgeschlagen → return (False, reason, details_dict)
```

**Wichtig:** `details_dict` enthält immer die tatsächlichen Marktdaten (Bid, Ask, OI beider Legs, berechneter Net Credit), auch bei Ablehnung. Diese Daten werden sowohl bei Trades als auch bei Rejections gespeichert.

### 4. Integration in `daily_picks`

Am **Ende** der bestehenden `daily_picks`-Funktion (nach Scoring, nach Ranking, nach Strikes-Empfehlung) wird für jeden Pick:

1. `check_tradability()` aufgerufen
2. Bei Erfolg → `shadow_tracker.log_trade()` mit allen Feldern inkl. Options-Marktdaten
3. Bei Ablehnung → `shadow_tracker.log_rejection()` mit Grund und Details

**Duplikat-Erkennung:** Gleicher Tag + gleiches Symbol + gleicher Short Strike + gleicher Long Strike = kein neuer Eintrag. Das verhindert Mehrfach-Logging bei wiederholten Aufrufen.

**Daily-Picks-Output anpassen:** Jeder Pick zeigt den Tradability-Status:

```
## #1 — AAPL | Pullback | Score 10.3
Strikes: Short $240 / Long $230 | Width $10
Credit: $2.45 (Bid $4.20 / Ask $1.75) | OI: 1,240 / 890
✅ TRADEABLE — Shadow Trade geloggt

## #2 — CVS | Pullback | Score 10.4
Strikes: Short $70 / Long $60 | Width $10
Credit: $0.85 | OI: 120 / 45
❌ NOT TRADEABLE — low_oi, low_credit
```

### 5. Vier neue MCP-Tools

Registriere diese in `mcp_server.py` mit den üblichen Alias-Patterns:

#### Tool 1: `shadow_review` (Alias: `shadow_review`)

Prüft alle offenen Shadow Trades gegen aktuelle Kurse und aktualisiert den Status.

**Parameter:**
| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|-------------|
| `resolve` | bool | true | Offene Trades gegen aktuelle Kurse prüfen |
| `status_filter` | string | 'all' | 'open' \| 'closed' \| 'all' |
| `strategy_filter` | string | null | Filter nach Strategie |
| `days_back` | int | 90 | Zeitraum in Tagen |

**Outcome-Resolution-Logik** (für jeden offenen Trade):

Die Resolution nutzt **echte Options-Chain-Daten von Tradier**, nicht nur den Aktienkurs. Das ist entscheidend, weil das PLAYBOOK einen 50%-Profit-Target-Exit als Standard-Rule vorsieht. Ohne den tatsächlichen Spread-Wert lässt sich nicht bestimmen, ob dieser Exit gegriffen hätte.

```
Für jeden offenen Shadow Trade:

1. Aktuelle Options-Chain von Tradier holen (Symbol, Expiration, right='P')
2. Short Put und Long Put anhand der gespeicherten Strikes finden
3. Historical Prices von Tradier holen (Logging-Datum bis heute)
4. price_min = Minimum der Schlusskurse

5. SPREAD-WERT BERECHNEN (aktuell):
   current_spread_value = short_put_ask - long_put_bid
   (Kosten um den Spread zurückzukaufen: Buy-to-Close Short at Ask, Sell-to-Close Long at Bid)

6. PROFIT-TARGET CHECK (50% des Credits):
   profit_target = est_credit * 0.50
   Wenn current_spread_value <= profit_target:
   → 'partial_profit' (50% Profit-Target erreicht)
   → Speichere price_at_50pct = aktueller Kurs
   → Speichere days_to_50pct = Tage seit Logging

7. STOP-LOSS CHECK (Spread-Wert >= 250% des Credits = Credit + 150%):
   stop_loss_value = est_credit * 2.50
   Wenn current_spread_value >= stop_loss_value:
   → 'stop_loss'

8. EXPIRATION CHECK (wenn expiration <= heute):
   - Chain nicht mehr verfügbar → Kursbasiert:
     - Kurs >= short_strike       → 'max_profit'
     - Kurs <= long_strike        → 'max_loss'
     - Dazwischen                 → 'partial_loss'

9. KURS-BASIERTER STOP-LOSS FALLBACK:
   (Falls Chain-Daten nicht verfügbar, z.B. Markt geschlossen)
   stop_trigger = short_strike - (spread_width * 0.3)
   Wenn price_min <= stop_trigger:
   → 'stop_loss'

10. Sonst → bleibt 'open'
```

**Priorität der Checks:** Profit-Target (6) vor Stop-Loss (7) vor Expiration (8) vor Kurs-Fallback (9). Falls die Options-Chain nicht verfügbar ist (API-Fehler, Markt geschlossen), fällt die Logik auf die kursbasierten Checks (8, 9) zurück. Trade bleibt 'open' wenn keine Daten verfügbar sind — kein falsches Resolving.

**API-Budget:** Ein Options-Chain-Call pro offenem Shadow Trade bei jedem `shadow_review`. Bei 10–15 offenen Trades akzeptabel. Bei >30 offenen Trades ggf. auf Tier-1-Trades beschränken oder Rate-Limiting beachten.

**P&L-Berechnung** (pro Spread, 1 Kontrakt = 100 Multiplikator):
- `partial_profit`: +(est_credit - current_spread_value) × 100 (typisch ~50% des Credits)
- `max_profit`: +est_credit × 100 (voller Credit, Spread wertlos verfallen)
- `stop_loss`: -(current_spread_value - est_credit) × 100 (oder -(est_credit × 1.5) × 100 bei Kurs-Fallback)
- `max_loss`: -(spread_width × 100 - est_credit × 100)
- `partial_loss`: +(est_credit × 100) - max(0, short_strike - price_at_expiry) × 100

**Neues DB-Feld** (zum Schema hinzufügen):
```sql
spread_value_at_resolve REAL,  -- Tatsächlicher Spread-Wert bei Resolution (Short Ask - Long Bid)
```

**Hinweis in der Ausgabe:** "P&L basierend auf echten Options-Chain-Preisen bei Review. Expiration-Outcomes kursbasiert."

**Output:** Markdown-Tabellen wie in der Strategie-Doku spezifiziert. Immer die Zusammenfassung mit Rejection-Quote anzeigen.

#### Tool 2: `shadow_stats` (Alias: `shadow_stats`)

Aggregierte Statistiken.

**Parameter:**
| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|-------------|
| `group_by` | string | 'strategy' | 'strategy' \| 'score_bucket' \| 'regime' \| 'month' \| 'symbol' \| 'tier' \| 'rejection_reason' |
| `min_trades` | int | 5 | Mindestanzahl für statistische Relevanz |

**Score-Buckets:** 9–10, 7–9, 5–7, <5

**Bei `group_by='rejection_reason'`:** Abfrage gegen `shadow_rejections`-Tabelle.

**Immer am Ende der Ausgabe:** Executability-Rate (Trades / (Trades + Rejections) × 100).

#### Tool 3: `shadow_log` (Alias: `shadow_log`)

Manueller Fallback zum Loggen eines Trades ohne daily_picks. Alle Trade-Felder als Parameter. Durchläuft trotzdem den Tradability Check.

#### Tool 4: `shadow_detail` (Alias: `shadow_detail`)

Detail-View eines einzelnen Shadow Trades.

**Parameter:** `trade_id` (string, UUID)

**Output:** Alle Felder des Trades inkl. Options-Marktdaten bei Logging, aktueller Kurs, Kursverlauf (Hoch/Tief/Aktuell), und Status.

### 6. Konfiguration in `settings.yaml`

Füge diesen Block hinzu:

```yaml
shadow_tracker:
  enabled: true
  auto_log_daily_picks: true
  auto_log_scans: false
  auto_log_min_score: 8.0
  db_path: "data/shadow_trades.db"

tradability_gate:
  min_net_credit: 2.00
  min_open_interest: 500
  min_bid: 0.10
  max_bid_ask_spread_pct: 30
```

---

## Implementierungs-Reihenfolge

Arbeite diese Schritte **sequenziell** ab. Jeder Schritt muss funktionieren und getestet sein, bevor der nächste beginnt.

| Schritt | Was | Testkriterium |
|---------|-----|---------------|
| 1 | `shadow_tracker.py`: DB-Schema, Init, CRUD-Funktionen | DB wird erstellt, Trade kann geschrieben und gelesen werden |
| 2 | `check_tradability()`: Tradier Chain-Abfrage + alle Prüfungen | Gibt für AAPL `tradeable=True` mit realistischen Details zurück. Gibt für einen illiquiden Small-Cap `tradeable=False` mit korrektem Grund zurück |
| 3 | Integration in `daily_picks`: Auto-Log + Rejection-Tracking | `daily_picks` Aufruf erzeugt Einträge in beiden Tabellen. Output zeigt ✅/❌ Status |
| 4 | `shadow_review` MCP-Tool: Outcome-Resolution | Kann offene Trades resolven. Status-Update in DB korrekt |
| 5 | `shadow_stats` MCP-Tool: Aggregation | Gruppierung nach allen group_by-Werten funktioniert. Rejection-Analyse liefert Daten |
| 6 | `shadow_log` + `shadow_detail` MCP-Tools | Manueller Log funktioniert. Detail-View zeigt alle Felder |
| 7 | Tests | Unit-Tests für check_tradability, resolve_trade, calculate_pnl. Integration-Test für daily_picks → Shadow Trade Pipeline |
| 8 | MCP-Tool-Registrierung in `mcp_server.py` | Alle 4 Tools erreichbar und funktional |

---

## Technische Vorgaben

- **Keine neuen Dependencies.** SQLite3, uuid, json, datetime — alles Standard-Bibliothek. Tradier-API über bestehende Funktionen.
- **SQLite WAL-Modus** aktivieren bei DB-Init: `PRAGMA journal_mode=WAL`
- **Fehlerbehandlung:** Wenn Tradier-API nicht erreichbar → Trade bleibt ungeloggt, Warnung im Output. Kein Abbruch von daily_picks.
- **Keine eigene Kurs-Datenbank.** Historical Prices bei jedem `shadow_review`-Aufruf frisch von Tradier holen. Bestehenden Cache nutzen falls vorhanden.
- **Logging:** Nutze das bestehende Logging-Setup des Projekts. Shadow Tracker Aktionen auf INFO-Level.

---

## Was NICHT gebaut werden soll

- Kein UI, kein Dashboard, kein Web-Interface
- Kein Real-Time-Monitoring oder Scheduler
- Keine Options-Preis-Simulation (kein Black-Scholes, keine Greeks über Zeit)
- Keine Alerts oder Notifications
- Kein automatisches Threshold-Tuning
- Kein Backtesting-Modus
- **Keine Änderungen am bestehenden Scoring, an Strategien, am Ensemble-Modell oder an der Filter-Kaskade.** Der Shadow Tracker ist ein Add-On, kein Refactoring.

---

## Wichtige Regel

**Niemals eigenständig Orders ausführen oder Trades ins Portfolio eintragen.** Der Shadow Tracker ist ein reines Beobachtungs- und Protokollierungssystem. Finale Entscheidung und Ausführung liegt bei Lars.

---

## Abnahmekriterien

Phase 1 ist fertig wenn:

1. `daily_picks` loggt automatisch Shadow Trades und Rejections
2. Jeder geloggte Shadow Trade hat echte Options-Marktdaten (Bid, Ask, OI)
3. `shadow_review` kann offene Trades resolven und P&L berechnen
4. `shadow_stats` zeigt Gruppierung nach Strategie, Score, Tier und Rejection-Grund
5. Daily-Picks-Output zeigt ✅ TRADEABLE / ❌ NOT TRADEABLE pro Pick
6. Alle Tests grün
7. CI grün (falls vorhanden)
