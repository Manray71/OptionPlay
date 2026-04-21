"""
christian_patterns.py — Referenz-Implementierung aus Christians bull_put_scanner

Quelle: bull_put_scanner/technical.py (3.774 Zeilen)
Extrahiert: 2026-04-21
Zweck: Algorithmus-Referenz für OptionPlay E.2b.3 Pattern-Erkennung

Diese Funktionen sind reine Algorithmen:
  Input:  Python-Listen (closes, highs, lows, volumes, opens)
  Output: Dicts mit Pattern-Erkennung und Signaltexten

NICHT 1:1 kopieren — OptionPlay hat eigene Datenstrukturen (numpy arrays,
async, Dataclasses). Logik, Schwellwerte und Bedingungen übernehmen.

Hilfsfunktionen (sma, rsi_series, obv_series) sind enthalten weil
bull_flag_analysis sie intern aufruft. OptionPlay hat eigene Versionen
in src/indicators/.
"""


def sma(closes: list, period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def rsi_series(closes: list, period: int = 14) -> list:
    """
    Wilder's Smoothed RSI (korrekte Implementierung).
    - Erster Wert: einfacher Durchschnitt der ersten `period` Änderungen
    - Folgewerte: Wilder's EMA-Smoothing (alpha = 1/period)
    Entspricht der Berechnung in TradingView, Bloomberg, Yahoo Finance.
    """
    vals = [50.0] * len(closes)
    if len(closes) < period + 1:
        return vals
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]

    # Seed: einfacher Durchschnitt der ersten `period` Änderungen
    gains_seed  = [d for d in deltas[:period] if d > 0]
    losses_seed = [-d for d in deltas[:period] if d < 0]
    avg_gain = sum(gains_seed)  / period if gains_seed  else 0.0
    avg_loss = sum(losses_seed) / period if losses_seed else 0.0

    def _rsi_from_avgs(ag, al):
        if ag < 1e-10 and al < 1e-10: return 50.0   # flat → neutral
        if al < 1e-10:                return 100.0   # nur Gewinne
        return round(100 - (100 / (1 + ag / al)), 1)

    vals[period] = _rsi_from_avgs(avg_gain, avg_loss)

    # Wilder's smoothing für alle weiteren Bars
    for i in range(period, len(deltas)):
        d = deltas[i]
        avg_gain = (avg_gain * (period - 1) + (d if d > 0 else 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + (-d if d < 0 else 0.0)) / period
        vals[i + 1] = _rsi_from_avgs(avg_gain, avg_loss)

    return vals



def obv_series(closes: list, volumes: list) -> list:
    if len(closes) != len(volumes) or len(closes) < 2:
        return [0.0] * len(closes)
    obv = [0.0]
    for i in range(1, len(closes)):
        if   closes[i] > closes[i-1]: obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i-1]: obv.append(obv[-1] - volumes[i])
        else:                          obv.append(obv[-1])
    return obv


def bull_flag_analysis(closes: list, volumes: list,
                       highs: list = None, lows: list = None) -> dict:
    """
    Erkennt Bull Flag Pattern in 2 Stufen:

    Stufe 1 — Flagge läuft (Einstieg möglich):
      Fahnenstange ≥ 5%, Rücksetzer max 30%, Volumen ≥ 20% geringer

    Stufe 2 — BREAKOUT IMMINENT (optimaler Einstieg):
      Zusätzlich: höhere Tiefs in Flagge + OBV steigt + Volumen zieht sich zusammen

    Returns dict mit bull_flag, breakout_imminent, Details.
    """
    result = {
        "bull_flag": False,
        "breakout_imminent": False,
        "flagpole_pct": 0.0,
        "retracement_pct": 0.0,
        "flag_bars": 0,
    }
    try:
        if len(closes) < 20 or len(volumes) < 20:
            return result

        # ── Fahnenstange: Peak in letzten 5-15 Tagen ─────────────────────────
        lookback = min(15, len(closes) - 5)
        peak_idx = closes.index(max(closes[-lookback:]), len(closes) - lookback)
        peak     = closes[peak_idx]
        base_idx = max(0, peak_idx - 10)
        base     = min(closes[base_idx:peak_idx + 1]) if base_idx < peak_idx else closes[base_idx]

        flagpole_pct = (peak / base - 1) * 100 if base > 0 else 0
        if flagpole_pct < 5.0:
            return result

        # ── Flagge: Rücksetzer max 30% (strenger als vorher) ─────────────────
        current     = closes[-1]
        retracement = (peak - current) / (peak - base) * 100 if (peak - base) > 0 else 0
        if retracement > 30 or retracement < 0:
            return result

        # ── Volumen: Flagge ≥ 20% geringer als Fahnenstange ─────────────────
        flag_bars    = len(closes) - 1 - peak_idx
        if flag_bars < 3:
            return result  # mindestens 3 Tage Flagge

        vol_flagpole = sum(volumes[base_idx:peak_idx + 1]) / max(peak_idx - base_idx, 1)
        vol_flag     = sum(volumes[peak_idx + 1:]) / max(flag_bars, 1)
        if vol_flag >= vol_flagpole * 0.80:
            return result

        # ── Stufe 1 bestätigt ────────────────────────────────────────────────
        result["bull_flag"]       = True
        result["flagpole_pct"]    = round(flagpole_pct, 1)
        result["retracement_pct"] = round(retracement, 1)
        result["flag_bars"]       = flag_bars
        result["vol_ratio"]       = round(vol_flag / max(vol_flagpole, 1), 2)

        # ── Stufe 2 — BREAKOUT IMMINENT ──────────────────────────────────────
        # Braucht highs + lows für höhere Tiefs Erkennung
        if highs is None or lows is None:
            return result
        if len(lows) != len(closes) or len(highs) != len(closes):
            return result

        try:
            flag_lows = lows[peak_idx + 1:]
            flag_vols = volumes[peak_idx + 1:]

            # Signal 1: Höhere Tiefs (mind. 3 Tage, 0.5% Toleranz)
            higher_lows = (
                len(flag_lows) >= 3 and
                all(flag_lows[i] >= flag_lows[i-1] * 0.995
                    for i in range(1, len(flag_lows)))
            )

            # Signal 2: Volumen kontrahiert (letzte 2 Tage < 70% Flaggen-Ø)
            if len(flag_vols) >= 3:
                vol_last2       = sum(flag_vols[-2:]) / 2
                vol_contracting = vol_last2 < vol_flag * 0.70
            else:
                vol_contracting = False

            # Signal 3: OBV steigt in der Flagge
            obv_all    = obv_series(closes, volumes)
            obv_rising = len(obv_all) >= 4 and obv_all[-1] > obv_all[-(flag_bars + 1)]

            # Signal 4: RSI erholt sich auf 50-65
            rsi_all        = rsi_series(closes, 14)
            rsi_recovering = 50 <= rsi_all[-1] <= 65

            # Bedingung: höhere Tiefs + Volumen fällt (Pflicht) + OBV oder RSI (eines)
            imminent_signals = sum([higher_lows, vol_contracting, obv_rising, rsi_recovering])
            imminent = higher_lows and vol_contracting and (obv_rising or rsi_recovering)

            if imminent:
                result["breakout_imminent"]  = True
                result["imminent_signals"]   = imminent_signals
                result["higher_lows"]        = higher_lows
                result["vol_contracting"]    = vol_contracting
                result["obv_rising_in_flag"] = obv_rising
                result["rsi_recovering"]     = rsi_recovering

        except Exception:
            pass  # Stufe 2 optional — Stufe 1 bleibt gültig

    except Exception:
        pass
    return result


def inside_bar_nr7(highs: list, lows: list) -> dict:
    """
    Erkennt Inside Bar und NR7 (Narrow Range 7) Pattern.

    Inside Bar: Hoch/Tief der aktuellen Kerze innerhalb der Vortageskerze
    NR7: Engste Tagesrange der letzten 7 Kerzen
    Beide signalisieren Konsolidierung vor großem Move.
    In Aufwärtstrend → Ausbruch nach oben wahrscheinlich.
    """
    result = {"inside_bar": False, "nr7": False, "signal": ""}
    try:
        if len(highs) < 8 or len(lows) < 8:
            return result

        # Inside Bar: aktuelle Kerze innerhalb Vortag
        curr_high, curr_low   = highs[-1], lows[-1]
        prev_high, prev_low   = highs[-2], lows[-2]
        inside_bar = curr_high <= prev_high and curr_low >= prev_low

        # NR7: Range der letzten 7 Tage — aktuell am engsten
        ranges     = [highs[i] - lows[i] for i in range(-7, 0)]
        curr_range = ranges[-1]
        nr7        = curr_range == min(ranges) and curr_range > 0

        result["inside_bar"] = inside_bar
        result["nr7"]        = nr7

        if inside_bar and nr7:
            result["signal"] = "🕯️ Inside Bar + NR7 — Ausbruch unmittelbar bevor"
        elif nr7:
            result["signal"] = "🕯️ NR7 — engste Range seit 7 Tagen, großer Move erwartet"
        elif inside_bar:
            result["signal"] = "🕯️ Inside Bar — Konsolidierung, Breakout in Vorbereitung"

    except Exception:
        pass
    return result


def bollinger_squeeze(closes: list, period: int = 20, mult: float = 2.0) -> dict:
    """
    Erkennt Bollinger Band Squeeze — Bänder ziehen sich zusammen.
    Signalisiert niedrige Volatilität vor großem Move.
    Squeeze + Aufwärtstrend = optimaler Bull Put Einstieg.
    """
    result = {"squeeze": False, "squeeze_releasing": False, "bandwidth": 0.0, "signal": ""}
    try:
        if len(closes) < period + 10:
            return result

        def _bb(data, n, m):
            mid   = sum(data[-n:]) / n
            std   = (sum((x - mid) ** 2 for x in data[-n:]) / n) ** 0.5
            return mid - m * std, mid, mid + m * std

        # Aktuelle Bandbreite
        lb, mb, ub    = _bb(closes, period, mult)
        bandwidth     = (ub - lb) / mb if mb > 0 else 0

        # Historische Bandbreiten (letzten 50 Tage)
        bandwidths = []
        for i in range(50, 0, -1):
            if len(closes) >= period + i:
                _lb, _mb, _ub = _bb(closes[:-i], period, mult)
                if _mb > 0:
                    bandwidths.append((_ub - _lb) / _mb)

        if not bandwidths:
            return result

        pct_rank = sum(1 for b in bandwidths if b < bandwidth) / len(bandwidths)

        # Squeeze: aktuelle Bandbreite im untersten 20% der letzten 50 Tage
        squeeze = pct_rank <= 0.20

        # Squeeze releasing: war gestern noch enger, heute breiter → Ausbruch beginnt
        if len(closes) >= period + 2:
            _lb2, _mb2, _ub2 = _bb(closes[:-1], period, mult)
            prev_bw = (_ub2 - _lb2) / _mb2 if _mb2 > 0 else 0
            squeeze_releasing = squeeze and bandwidth > prev_bw * 1.05

        result["squeeze"]           = squeeze
        result["squeeze_releasing"] = squeeze_releasing
        result["bandwidth"]         = round(bandwidth * 100, 2)
        result["bandwidth_pct_rank"] = round(pct_rank * 100, 0)

        if squeeze_releasing:
            result["signal"] = f"⚙️ BB Squeeze löst sich — Ausbruch läuft (BW {bandwidth*100:.1f}%)"
        elif squeeze:
            result["signal"] = f"⚙️ BB Squeeze aktiv — großer Move bevorsteht (BW {bandwidth*100:.1f}%)"

    except Exception:
        pass
    return result


def post_earnings_drift(closes: list, days_since_earnings: int) -> dict:
    """
    Erkennt Post-Earnings Announcement Drift (PEAD).
    Aktien die gut berichten driften oft 5-15 Tage weiter nach oben.

    Bedingungen:
    - Earnings vor 1-10 Tagen
    - Seitdem konsistenter Aufwärtstrend (mind. 60% der Tage positiv)
    - Gesamtbewegung seit Earnings positiv

    Für Bull Put: sicherer Einstieg — Institutionen kaufen den Drift
    """
    result = {"pead_active": False, "drift_pct": 0.0, "signal": ""}
    try:
        if days_since_earnings is None or days_since_earnings <= 0:
            return result
        if days_since_earnings > 10:
            return result  # zu lange her
        if len(closes) < days_since_earnings + 2:
            return result

        # Preisbewegung seit Earnings
        pre_earnings_close = closes[-(days_since_earnings + 1)]
        current_close      = closes[-1]
        drift_pct          = (current_close / pre_earnings_close - 1) * 100

        # Nur positiver Drift relevant
        if drift_pct <= 1.0:
            return result

        # Konsistenz: mind. 60% der Tage positiv seit Earnings
        drift_closes  = closes[-(days_since_earnings + 1):]
        positive_days = sum(1 for i in range(1, len(drift_closes))
                           if drift_closes[i] > drift_closes[i-1])
        consistency   = positive_days / max(len(drift_closes) - 1, 1)

        if consistency < 0.60:
            return result

        result["pead_active"]  = True
        result["drift_pct"]    = round(drift_pct, 1)
        result["drift_days"]   = days_since_earnings
        result["consistency"]  = round(consistency * 100, 0)
        result["signal"]       = (
            f"📅 Post-Earnings Drift +{drift_pct:.1f}% "
            f"({days_since_earnings}d seit Earnings, {consistency*100:.0f}% konsistent)"
        )

    except Exception:
        pass
    return result


def three_bar_play(opens: list, highs: list, lows: list,
                   closes: list, volumes: list) -> dict:
    """
    Erkennt 3-Bar Play: 3 aufeinanderfolgende bullische Kerzen mit
    steigendem Volumen und höheren Schlusskursen.

    Bedingungen:
    1. Alle 3 Kerzen bullisch (close > open)
    2. Jede Kerze schließt höher als die vorherige
    3. Jede Kerze schließt in oberer Hälfte der Tagesrange
    4. Volumen steigt über alle 3 Bars
    5. Keine der Kerzen hat langen oberen Docht (< 30% der Range)
    """
    result = {"three_bar_play": False, "signal": ""}
    try:
        if len(closes) < 5 or len(opens) < 5:
            return result

        # Letzte 3 Kerzen
        for offset in range(0, 3):  # prüfe aktuelle + 1-2 Tage zurück
            i1, i2, i3 = -(3 + offset), -(2 + offset), -(1 + offset)

            o1, h1, l1, c1, v1 = opens[i1], highs[i1], lows[i1], closes[i1], volumes[i1]
            o2, h2, l2, c2, v2 = opens[i2], highs[i2], lows[i2], closes[i2], volumes[i2]
            o3, h3, l3, c3, v3 = opens[i3], highs[i3], lows[i3], closes[i3], volumes[i3]

            # 1. Alle bullisch
            if not (c1 > o1 and c2 > o2 and c3 > o3):
                continue

            # 2. Höhere Schlusskurse
            if not (c2 > c1 and c3 > c2):
                continue

            # 3. Schluss in oberer Hälfte der Range
            def upper_half(o, h, l, c):
                rng = h - l
                return rng > 0 and c >= l + rng * 0.5

            if not (upper_half(o1,h1,l1,c1) and upper_half(o2,h2,l2,c2) and upper_half(o3,h3,l3,c3)):
                continue

            # 4. Steigendes Volumen
            if not (v2 > v1 and v3 > v2):
                continue

            # 5. Kein langer oberer Docht (< 30% der Kerzenrange)
            def short_upper_wick(h, c, o):
                body = abs(c - o)
                wick = h - max(c, o)
                return body > 0 and wick <= body * 0.50

            if not (short_upper_wick(h1,c1,o1) and short_upper_wick(h2,c2,o2) and short_upper_wick(h3,c3,o3)):
                continue

            move_pct = round((c3 / c1 - 1) * 100, 1)
            result["three_bar_play"] = True
            result["move_pct"]       = move_pct
            result["signal"]         = f"📈 3-Bar Play (+{move_pct}% in 3 Tagen, Volumen steigend)"
            break

    except Exception:
        pass
    return result


def golden_pocket(closes: list, highs: list, lows: list,
                  lookback: int = 60) -> dict:
    """
    Erkennt Golden Pocket Retracement (Fibonacci 50-65%).

    Logik:
    1. Swing High: höchster Schlusskurs in letzten `lookback` Tagen
    2. Swing Low: tiefster Schlusskurs nach dem Hoch (mind. 5 Tage danach)
    3. Aktueller Preis im Golden Pocket: 50-65% Retracement
    4. Preis erholt sich (heute > gestern)
    """
    result = {"golden_pocket": False, "retracement_pct": 0.0, "signal": ""}
    try:
        if len(closes) < 30:
            return result

        window = closes[-lookback:]
        n      = len(window)

        # Swing High: höchster Schlusskurs im Window
        swing_high_idx = window.index(max(window))

        # Mind. 5 Tage nach dem Hoch für validen Swing Low
        if n - swing_high_idx < 5:
            return result

        swing_high = window[swing_high_idx]

        # Swing Low: tiefster Punkt nach dem Hoch, aktuellen Tag ausschließen
        after_peak = window[swing_high_idx + 1: -1]
        if len(after_peak) < 3:
            return result

        swing_low   = min(after_peak)
        swing_range = swing_high - swing_low

        # Mindest-Rücksetzer: 5% des Swing Highs
        if swing_range <= 0 or swing_range / swing_high < 0.05:
            return result

        # Golden Pocket Zone: 50% bis 65% Retracement
        gp_high = swing_high - swing_range * 0.50
        gp_low  = swing_high - swing_range * 0.65

        current = closes[-1]
        prev    = closes[-2]

        in_pocket  = gp_low <= current <= gp_high
        recovering = current > prev

        if in_pocket and recovering:
            retracement_pct = round((swing_high - current) / swing_range * 100, 1)
            result["golden_pocket"]   = True
            result["retracement_pct"] = retracement_pct
            result["swing_high"]      = round(swing_high, 2)
            result["swing_low"]       = round(swing_low, 2)
            result["gp_low"]          = round(gp_low, 2)
            result["gp_high"]         = round(gp_high, 2)
            result["signal"]          = (
                f"📐 Golden Pocket {retracement_pct:.1f}% Fib "
                f"(${gp_low:.1f}-${gp_high:.1f}) — Institutioneller Support"
            )

    except Exception:
        pass
    return result


def weekly_vwap_reclaim(closes: list, highs: list, lows: list,
                        volumes: list, weeks: int = 2) -> dict:
    """
    Erkennt Weekly VWAP Reclaim.
    Verwendet typischen Preis (H+L+C)/3 gewichtet mit Volumen.

    VWAP Reclaim: Preis war unter Weekly VWAP, jetzt darüber.
    Zeigt dass Institutionen Support etablieren.

    weeks=2: VWAP der letzten 2 Wochen (10 Handelstage)
    """
    result = {"vwap_reclaim": False, "above_vwap": False,
              "vwap": 0.0, "signal": ""}
    try:
        days = weeks * 5  # Handelstage
        if len(closes) < days + 5:
            return result

        # Weekly VWAP: typischer Preis × Volumen / Gesamtvolumen
        typical = [(highs[i] + lows[i] + closes[i]) / 3
                   for i in range(-days, 0)]
        vols_w  = volumes[-days:]
        total_vol = sum(vols_w)

        if total_vol <= 0:
            return result

        vwap = sum(t * v for t, v in zip(typical, vols_w)) / total_vol
        current  = closes[-1]
        prev     = closes[-2]
        prev2    = closes[-3] if len(closes) >= 3 else closes[-2]

        above_vwap = current > vwap

        # VWAP Reclaim: gestern oder vorgestern unter VWAP, heute drüber
        was_below = prev < vwap or prev2 < vwap
        reclaim   = above_vwap and was_below and current > prev

        result["vwap"]        = round(vwap, 2)
        result["above_vwap"]  = above_vwap
        result["vwap_reclaim"] = reclaim
        result["pct_above"]   = round((current / vwap - 1) * 100, 2)

        if reclaim:
            result["signal"] = (
                f"📊 VWAP Reclaim (${vwap:.1f}) — "
                f"Institutioneller Support bestätigt"
            )
        elif above_vwap:
            result["signal"] = f"📊 Über Weekly VWAP (${vwap:.1f})"

    except Exception:
        pass
    return result




# ======================================================================
# SCORING-REFERENZ (nicht als standalone ausführbar — Kontext-Variablen)
# Zeigt die exakten Punkt-Werte für jedes Signal
# ======================================================================

# --- Fast Score Breakout-Punkte (aus score_fast_close, L3558-3700) ---
#
# Fast-Closer-Profil (RVOL+ADX+ROC):     +30
# Momentum-Bonus >= 15:                    +18
# Momentum-Bonus >= 10:                    +10
# Momentum Score >= 85:                    +25
# Momentum Score >= 75:                    +15
# Momentum Score >= 60:                    +6
# RVOL >= 2.0:                             +15
# RVOL >= 1.5:                             +10
# RVOL >= 1.2:                             +5
# RVOL 3d >= 1.5:                          +12
# RVOL 3d >= 1.2:                          +6
# ROC >= 5%:                               +12
# ROC >= 3%:                               +8
# ROC >= 1.5%:                             +3
# ADX >= 30:                               +10
# ADX >= 20:                               +5
#
# --- Breakout Patterns ---
# BREAKOUT IMMINENT (Bull Flag Stufe 2):   +25
# PRE-BREAKOUT Phase 2 (Wyckoff):          +20
# VWAP Reclaim:                            +15
# PEAD (Post-Earnings Drift):              +15
# Bull Flag (Stufe 1):                     +12
# 3-Bar Play:                              +12
# BB Squeeze released:                     +12
# NR7 + Inside Bar:                        +10
# Golden Pocket+ (≥2 Confluence):          +7 bis +10
#
# RSI Cross >50:                           +10
# Cross 20/50 bull:                        +8
# RSI 50-60 + Cross:                       +10
# Intraday >= 2%:                          +10
# RRG Fast LEADING:                        +10
# RRG Fast IMPROVING:                      +6
#
# --- Formel ---
# final_score = bps_score + fast_score × 1.5


# ======================================================================
# PRE-BREAKOUT Phase 2 — Akkumulations-Erkennung
# (aus score_technicals, L1895-1942)
# Nicht standalone — zeigt die kombinierte Bedingung
# ======================================================================
#
# Phase 2 (Breakout unmittelbar bevor):
#   CMF > 0.10 AND cmf_rising
#   AND MFI 50-65 AND mfi_rising
#   AND OBV > SMA20
#   AND RSI 50-65
#   → Score +2.5 (×8 Multiplikator = +20 im Gesamt-Score)
#
# Phase 1 (Stille Akkumulation):
#   CMF > 0.05 AND cmf_rising
#   AND mfi_rising
#   AND (OBV cross SMA20 OR OBV > SMA20)
#   AND RSI >= 45
#   → Score +1.5 (×8 = +12 im Gesamt-Score)
#   HINWEIS: Phase 1 wurde aus SIGNAL_ICONS entfernt (zu früh)


# ======================================================================
# K.O.-Kaskade (aus phase2_score_only, scanner.py)
# ======================================================================
#
# 1. History < 55 Tage → Datenmangel → None
# 2. RSI > 80 → krass überkauft → None
# 3. RSI 65-80 + 10d-Peak >= 70 + Drop >= 5 → Pullback-Falle → None
# 4. Intraday <= -4% → aktiver Crash → None
# 5. Post-Earnings Cooldown (0-2d nach Earnings) → None
# 6. Earnings < 12 Tage → Event-Risiko → None
# 7. IV Rank = 0 → keine Daten → None
# 8. IV Rank < 35 → kein Credit → None
# 9. Geschätzter Credit < $0.60 → nicht wirtschaftlich → None
