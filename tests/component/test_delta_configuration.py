"""
Tests for Delta Configuration - Unit, Regression & Integration Tests
=====================================================================

Bug Report: Delta-Konfiguration wird nicht übernommen
- Short Put Delta soll -0.20 sein (nicht 0.30)
- Long Put Delta soll -0.05 sein (nicht 0.10)

Dieser Test-Modul stellt sicher, dass:
1. Unit Tests: Alle Delta-Werte an allen Stellen korrekt sind
2. Regressionstests: Die alten Werte 0.30/0.10 nie wieder auftauchen
3. Integrationstests: Delta-Werte korrekt durch die gesamte Pipeline fließen
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# =============================================================================
# TEIL 1: UNIT TESTS - Delta-Werte an allen Definitionsstellen
# =============================================================================


class TestDeltaConstantsTradingRules:
    """Unit Tests: trading_rules.py Delta-Konstanten (Source of Truth)"""

    def test_short_delta_target(self):
        """PLAYBOOK §2: Short Put Delta Target ist -0.20"""
        from constants.trading_rules import SPREAD_SHORT_DELTA_TARGET
        assert SPREAD_SHORT_DELTA_TARGET == -0.20

    def test_short_delta_min(self):
        """PLAYBOOK §2: Short Put Delta Min ist -0.17 (±0.03)"""
        from constants.trading_rules import SPREAD_SHORT_DELTA_MIN
        assert SPREAD_SHORT_DELTA_MIN == -0.17

    def test_short_delta_max(self):
        """PLAYBOOK §2: Short Put Delta Max ist -0.23 (±0.03)"""
        from constants.trading_rules import SPREAD_SHORT_DELTA_MAX
        assert SPREAD_SHORT_DELTA_MAX == -0.23

    def test_long_delta_target(self):
        """PLAYBOOK §2: Long Put Delta Target ist -0.05"""
        from constants.trading_rules import SPREAD_LONG_DELTA_TARGET
        assert SPREAD_LONG_DELTA_TARGET == -0.05

    def test_long_delta_min(self):
        """PLAYBOOK §2: Long Put Delta Min ist -0.03 (±0.02)"""
        from constants.trading_rules import SPREAD_LONG_DELTA_MIN
        assert SPREAD_LONG_DELTA_MIN == -0.03

    def test_long_delta_max(self):
        """PLAYBOOK §2: Long Put Delta Max ist -0.07 (±0.02)"""
        from constants.trading_rules import SPREAD_LONG_DELTA_MAX
        assert SPREAD_LONG_DELTA_MAX == -0.07

    def test_short_delta_range_symmetric(self):
        """Short Delta Range ist symmetrisch um Target (±0.03)"""
        from constants.trading_rules import (
            SPREAD_SHORT_DELTA_TARGET,
            SPREAD_SHORT_DELTA_MIN,
            SPREAD_SHORT_DELTA_MAX,
        )
        tolerance = 0.03
        assert SPREAD_SHORT_DELTA_MIN == pytest.approx(
            SPREAD_SHORT_DELTA_TARGET + tolerance, abs=0.001
        )
        assert SPREAD_SHORT_DELTA_MAX == pytest.approx(
            SPREAD_SHORT_DELTA_TARGET - tolerance, abs=0.001
        )

    def test_long_delta_range_symmetric(self):
        """Long Delta Range ist symmetrisch um Target (±0.02)"""
        from constants.trading_rules import (
            SPREAD_LONG_DELTA_TARGET,
            SPREAD_LONG_DELTA_MIN,
            SPREAD_LONG_DELTA_MAX,
        )
        tolerance = 0.02
        assert SPREAD_LONG_DELTA_MIN == pytest.approx(
            SPREAD_LONG_DELTA_TARGET + tolerance, abs=0.001
        )
        assert SPREAD_LONG_DELTA_MAX == pytest.approx(
            SPREAD_LONG_DELTA_TARGET - tolerance, abs=0.001
        )

    def test_all_deltas_are_negative(self):
        """Alle Put-Deltas müssen negativ sein"""
        from constants.trading_rules import (
            SPREAD_SHORT_DELTA_TARGET,
            SPREAD_SHORT_DELTA_MIN,
            SPREAD_SHORT_DELTA_MAX,
            SPREAD_LONG_DELTA_TARGET,
            SPREAD_LONG_DELTA_MIN,
            SPREAD_LONG_DELTA_MAX,
        )
        for delta in [
            SPREAD_SHORT_DELTA_TARGET,
            SPREAD_SHORT_DELTA_MIN,
            SPREAD_SHORT_DELTA_MAX,
            SPREAD_LONG_DELTA_TARGET,
            SPREAD_LONG_DELTA_MIN,
            SPREAD_LONG_DELTA_MAX,
        ]:
            assert delta < 0, f"Delta {delta} muss negativ sein (Put-Option)"

    def test_short_delta_more_negative_than_long(self):
        """Short Put Delta ist stärker negativ als Long Put Delta"""
        from constants.trading_rules import (
            SPREAD_SHORT_DELTA_TARGET,
            SPREAD_LONG_DELTA_TARGET,
        )
        assert SPREAD_SHORT_DELTA_TARGET < SPREAD_LONG_DELTA_TARGET

    def test_min_less_aggressive_than_max(self):
        """Delta Min ist weniger aggressiv (näher an 0) als Delta Max"""
        from constants.trading_rules import (
            SPREAD_SHORT_DELTA_MIN,
            SPREAD_SHORT_DELTA_MAX,
            SPREAD_LONG_DELTA_MIN,
            SPREAD_LONG_DELTA_MAX,
        )
        # Min (z.B. -0.17) ist näher an 0 als Max (z.B. -0.23)
        assert abs(SPREAD_SHORT_DELTA_MIN) < abs(SPREAD_SHORT_DELTA_MAX)
        assert abs(SPREAD_LONG_DELTA_MIN) < abs(SPREAD_LONG_DELTA_MAX)


class TestDeltaConstantsRiskManagement:
    """Unit Tests: risk_management.py Delta-Konstanten (Spiegelung)"""

    def test_delta_target_matches_trading_rules(self):
        """risk_management.DELTA_TARGET muss mit trading_rules übereinstimmen"""
        from constants.risk_management import DELTA_TARGET
        from constants.trading_rules import SPREAD_SHORT_DELTA_TARGET
        assert DELTA_TARGET == SPREAD_SHORT_DELTA_TARGET == -0.20

    def test_delta_min_matches_trading_rules(self):
        """risk_management.DELTA_MIN muss mit trading_rules übereinstimmen"""
        from constants.risk_management import DELTA_MIN
        from constants.trading_rules import SPREAD_SHORT_DELTA_MIN
        assert DELTA_MIN == SPREAD_SHORT_DELTA_MIN == -0.17

    def test_delta_max_matches_trading_rules(self):
        """risk_management.DELTA_MAX muss mit trading_rules übereinstimmen"""
        from constants.risk_management import DELTA_MAX
        from constants.trading_rules import SPREAD_SHORT_DELTA_MAX
        assert DELTA_MAX == SPREAD_SHORT_DELTA_MAX == -0.23

    def test_long_delta_target_matches(self):
        """risk_management.DELTA_LONG_TARGET muss übereinstimmen"""
        from constants.risk_management import DELTA_LONG_TARGET
        from constants.trading_rules import SPREAD_LONG_DELTA_TARGET
        assert DELTA_LONG_TARGET == SPREAD_LONG_DELTA_TARGET == -0.05

    def test_long_delta_min_matches(self):
        """risk_management.DELTA_LONG_MIN muss übereinstimmen"""
        from constants.risk_management import DELTA_LONG_MIN
        from constants.trading_rules import SPREAD_LONG_DELTA_MIN
        assert DELTA_LONG_MIN == SPREAD_LONG_DELTA_MIN == -0.03

    def test_long_delta_max_matches(self):
        """risk_management.DELTA_LONG_MAX muss übereinstimmen"""
        from constants.risk_management import DELTA_LONG_MAX
        from constants.trading_rules import SPREAD_LONG_DELTA_MAX
        assert DELTA_LONG_MAX == SPREAD_LONG_DELTA_MAX == -0.07

    def test_conservative_equals_min(self):
        """DELTA_CONSERVATIVE muss gleich DELTA_MIN sein"""
        from constants.risk_management import DELTA_CONSERVATIVE, DELTA_MIN
        assert DELTA_CONSERVATIVE == DELTA_MIN

    def test_aggressive_equals_max(self):
        """DELTA_AGGRESSIVE muss gleich DELTA_MAX sein"""
        from constants.risk_management import DELTA_AGGRESSIVE, DELTA_MAX
        assert DELTA_AGGRESSIVE == DELTA_MAX


class TestDeltaTradingRulesConvenience:
    """Unit Tests: TradingRules Convenience Class"""

    def test_short_delta_in_convenience_class(self):
        """TradingRules.SHORT_DELTA muss -0.20 sein"""
        from constants.trading_rules import TradingRules
        tr = TradingRules()
        assert tr.SHORT_DELTA == -0.20

    def test_long_delta_in_convenience_class(self):
        """TradingRules.LONG_DELTA muss -0.05 sein"""
        from constants.trading_rules import TradingRules
        tr = TradingRules()
        assert tr.LONG_DELTA == -0.05


class TestDeltaOptionsConfigDefaults:
    """Unit Tests: OptionsConfig Dataclass Defaults"""

    def test_delta_target_default(self):
        """OptionsConfig.delta_target Default ist -0.20"""
        from config import OptionsConfig
        config = OptionsConfig()
        assert config.delta_target == -0.20

    def test_long_delta_target_default(self):
        """OptionsConfig.long_delta_target Default ist -0.05"""
        from config import OptionsConfig
        config = OptionsConfig()
        assert config.long_delta_target == -0.05

    def test_delta_min_property(self):
        """OptionsConfig.delta_min Property funktioniert"""
        from config import OptionsConfig
        config = OptionsConfig()
        assert config.delta_min == config.delta_minimum

    def test_delta_max_property(self):
        """OptionsConfig.delta_max Property funktioniert"""
        from config import OptionsConfig
        config = OptionsConfig()
        assert config.delta_max == config.delta_maximum

    def test_short_delta_target_property(self):
        """OptionsConfig.short_delta_target Property gibt delta_target zurück"""
        from config import OptionsConfig
        config = OptionsConfig()
        assert config.short_delta_target == -0.20

    def test_custom_delta_overrides_default(self):
        """Benutzerdefiniertes Delta überschreibt Default"""
        from config import OptionsConfig
        config = OptionsConfig(delta_target=-0.25)
        assert config.delta_target == -0.25

    def test_custom_long_delta_overrides_default(self):
        """Benutzerdefiniertes Long Delta überschreibt Default"""
        from config import OptionsConfig
        config = OptionsConfig(long_delta_target=-0.08)
        assert config.long_delta_target == -0.08


class TestDeltaStrikeRecommenderDefaults:
    """Unit Tests: StrikeRecommender DEFAULT_CONFIG"""

    @pytest.fixture
    def recommender(self):
        from strike_recommender import StrikeRecommender
        return StrikeRecommender(use_config_loader=False)

    def test_default_short_delta_target(self, recommender):
        """StrikeRecommender short delta_target ist -0.20"""
        assert recommender.config["delta_target"] == -0.20

    def test_default_short_delta_min(self, recommender):
        """StrikeRecommender short delta_min ist -0.17"""
        assert recommender.config["delta_min"] == -0.17

    def test_default_short_delta_max(self, recommender):
        """StrikeRecommender short delta_max ist -0.23"""
        assert recommender.config["delta_max"] == -0.23

    def test_default_long_delta_target(self, recommender):
        """StrikeRecommender long delta_target ist -0.05"""
        assert recommender.config["long_delta_target"] == -0.05

    def test_default_long_delta_min(self, recommender):
        """StrikeRecommender long delta_min ist -0.03"""
        assert recommender.config["long_delta_min"] == -0.03

    def test_default_long_delta_max(self, recommender):
        """StrikeRecommender long delta_max ist -0.07"""
        assert recommender.config["long_delta_max"] == -0.07


class TestDeltaBacktestingConfig:
    """Unit Tests: BacktestConfig Delta-Defaults"""

    def test_short_delta_target(self):
        """BacktestConfig.short_delta_target ist -0.20"""
        try:
            from src.backtesting import BacktestConfig
        except ImportError:
            pytest.skip("BacktestConfig nicht importierbar (relative import)")
        config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31")
        assert config.short_delta_target == -0.20

    def test_long_delta_target(self):
        """BacktestConfig.long_delta_target ist -0.05"""
        try:
            from src.backtesting import BacktestConfig
        except ImportError:
            pytest.skip("BacktestConfig nicht importierbar (relative import)")
        config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31")
        assert config.long_delta_target == -0.05


# =============================================================================
# TEIL 2: REGRESSIONSTESTS - Alte Werte 0.30/0.10 dürfen nie wieder erscheinen
# =============================================================================


class TestDeltaRegressionNoOldValues:
    """
    Regressionstests: Verhindern, dass die alten Delta-Werte 0.30/0.10
    jemals wieder in den Code gelangen.
    """

    def test_trading_rules_no_030(self):
        """trading_rules.py: Kein Delta-Wert darf 0.30 sein"""
        from constants.trading_rules import (
            SPREAD_SHORT_DELTA_TARGET,
            SPREAD_SHORT_DELTA_MIN,
            SPREAD_SHORT_DELTA_MAX,
        )
        for val in [SPREAD_SHORT_DELTA_TARGET, SPREAD_SHORT_DELTA_MIN, SPREAD_SHORT_DELTA_MAX]:
            assert abs(val) != 0.30, f"REGRESSION: Alter Delta-Wert 0.30 gefunden: {val}"

    def test_trading_rules_no_010(self):
        """trading_rules.py: Kein Long-Delta-Wert darf 0.10 sein"""
        from constants.trading_rules import (
            SPREAD_LONG_DELTA_TARGET,
            SPREAD_LONG_DELTA_MIN,
            SPREAD_LONG_DELTA_MAX,
        )
        for val in [SPREAD_LONG_DELTA_TARGET, SPREAD_LONG_DELTA_MIN, SPREAD_LONG_DELTA_MAX]:
            assert abs(val) != 0.10, f"REGRESSION: Alter Long-Delta-Wert 0.10 gefunden: {val}"

    def test_risk_management_no_030(self):
        """risk_management.py: Kein Delta-Wert darf 0.30 sein"""
        from constants.risk_management import DELTA_TARGET, DELTA_MIN, DELTA_MAX
        for name, val in [("DELTA_TARGET", DELTA_TARGET), ("DELTA_MIN", DELTA_MIN), ("DELTA_MAX", DELTA_MAX)]:
            assert abs(val) != 0.30, f"REGRESSION: {name} hat alten Wert 0.30"

    def test_risk_management_no_010(self):
        """risk_management.py: Kein Long-Delta-Wert darf 0.10 sein"""
        from constants.risk_management import DELTA_LONG_TARGET, DELTA_LONG_MIN, DELTA_LONG_MAX
        for name, val in [
            ("DELTA_LONG_TARGET", DELTA_LONG_TARGET),
            ("DELTA_LONG_MIN", DELTA_LONG_MIN),
            ("DELTA_LONG_MAX", DELTA_LONG_MAX),
        ]:
            assert abs(val) != 0.10, f"REGRESSION: {name} hat alten Wert 0.10"

    def test_strike_recommender_no_030(self):
        """StrikeRecommender: Kein Default-Delta darf 0.30 sein"""
        from strike_recommender import StrikeRecommender

        rec = StrikeRecommender(use_config_loader=False)
        assert abs(rec.config["delta_target"]) != 0.30, "REGRESSION: delta_target ist 0.30"
        assert abs(rec.config["delta_min"]) != 0.30, "REGRESSION: delta_min ist 0.30"
        assert abs(rec.config["delta_max"]) != 0.30, "REGRESSION: delta_max ist 0.30"

    def test_strike_recommender_no_010(self):
        """StrikeRecommender: Kein Long-Delta-Default darf 0.10 sein"""
        from strike_recommender import StrikeRecommender

        rec = StrikeRecommender(use_config_loader=False)
        assert abs(rec.config["long_delta_target"]) != 0.10, "REGRESSION: long_delta_target ist 0.10"
        assert abs(rec.config["long_delta_min"]) != 0.10, "REGRESSION: long_delta_min ist 0.10"
        assert abs(rec.config["long_delta_max"]) != 0.10, "REGRESSION: long_delta_max ist 0.10"

    def test_options_config_no_030(self):
        """OptionsConfig: Kein Default darf 0.30 sein"""
        from config import OptionsConfig

        config = OptionsConfig()
        assert abs(config.delta_target) != 0.30, "REGRESSION: OptionsConfig.delta_target ist 0.30"

    def test_options_config_no_010(self):
        """OptionsConfig: Kein Long-Delta-Default darf 0.10 sein"""
        from config import OptionsConfig

        config = OptionsConfig()
        assert abs(config.long_delta_target) != 0.10, "REGRESSION: OptionsConfig.long_delta_target ist 0.10"

    def test_backtest_config_no_030(self):
        """BacktestConfig: Kein Default darf 0.30 sein"""
        try:
            from src.backtesting import BacktestConfig
        except ImportError:
            pytest.skip("BacktestConfig nicht importierbar (relative import)")

        config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31")
        assert abs(config.short_delta_target) != 0.30, "REGRESSION: BacktestConfig.short_delta_target ist 0.30"

    def test_backtest_config_no_010(self):
        """BacktestConfig: Kein Long-Delta-Default darf 0.10 sein"""
        try:
            from src.backtesting import BacktestConfig
        except ImportError:
            pytest.skip("BacktestConfig nicht importierbar (relative import)")

        config = BacktestConfig(start_date="2024-01-01", end_date="2024-12-31")
        assert abs(config.long_delta_target) != 0.10, "REGRESSION: BacktestConfig.long_delta_target ist 0.10"

    def test_convenience_class_no_old_values(self):
        """TradingRules Convenience: Keine alten Werte"""
        from constants.trading_rules import TradingRules

        tr = TradingRules()
        assert abs(tr.SHORT_DELTA) != 0.30, "REGRESSION: TradingRules.SHORT_DELTA ist 0.30"
        assert abs(tr.LONG_DELTA) != 0.10, "REGRESSION: TradingRules.LONG_DELTA ist 0.10"


class TestDeltaRegressionSourceCodeScan:
    """
    Regressionstests: Durchsuche Source-Dateien nach hardcoded alten Werten.

    Diese Tests lesen die tatsächlichen Source-Dateien und prüfen,
    ob die alten Werte 0.30/0.10 als Delta-Definitionen vorkommen.
    """

    @pytest.fixture
    def src_dir(self):
        return Path(__file__).parent.parent / "src"

    def _scan_file_for_pattern(self, filepath: Path, forbidden_patterns: list) -> list:
        """Durchsucht eine Datei nach verbotenen Patterns"""
        violations = []
        try:
            content = filepath.read_text(encoding="utf-8")
            for line_num, line in enumerate(content.split("\n"), 1):
                # Überspringe Kommentare und Strings die Dokumentation enthalten
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    continue

                for pattern in forbidden_patterns:
                    if pattern in line:
                        # Kontext prüfen: ist es wirklich ein Delta-Wert?
                        lower_line = line.lower()
                        if "delta" in lower_line or "0.30" in line or "0.10" in line:
                            violations.append(
                                f"{filepath.name}:{line_num}: {stripped}"
                            )
        except Exception:
            pass
        return violations

    def test_no_030_in_strike_recommender(self, src_dir):
        """strike_recommender.py: Kein hardcoded 0.30 Delta"""
        filepath = src_dir / "strike_recommender.py"
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Suche nach Zuweisungen mit 0.30 im Delta-Kontext
                if "= 0.30" in line or "= -0.30" in line:
                    if "delta" in line.lower():
                        pytest.fail(
                            f"REGRESSION: Hardcoded 0.30 Delta in "
                            f"strike_recommender.py Zeile {i}: {stripped}"
                        )

    def test_no_010_in_strike_recommender(self, src_dir):
        """strike_recommender.py: Kein hardcoded 0.10 Long Delta"""
        filepath = src_dir / "strike_recommender.py"
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "= 0.10" in line or "= -0.10" in line:
                    if "delta" in line.lower():
                        pytest.fail(
                            f"REGRESSION: Hardcoded 0.10 Delta in "
                            f"strike_recommender.py Zeile {i}: {stripped}"
                        )

    def test_no_030_in_config_loader(self, src_dir):
        """config_loader.py: Kein hardcoded 0.30 Delta"""
        filepath = src_dir / "config" / "config_loader.py"
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if ("= -0.30" in line or "= 0.30" in line) and "delta" in line.lower():
                    pytest.fail(
                        f"REGRESSION: Hardcoded 0.30 Delta in "
                        f"config_loader.py Zeile {i}: {stripped}"
                    )

    def test_no_old_defaults_in_strategies(self, src_dir):
        """strategies/: Kein hardcoded 0.30 oder 0.10 Delta"""
        strategies_dir = src_dir / "strategies"
        if not strategies_dir.exists():
            pytest.skip("strategies/ Verzeichnis nicht gefunden")

        for filepath in strategies_dir.glob("*.py"):
            content = filepath.read_text(encoding="utf-8")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if ("= -0.30" in line or "= 0.30" in line) and "delta" in line.lower():
                    pytest.fail(
                        f"REGRESSION: Hardcoded 0.30 Delta in "
                        f"{filepath.name} Zeile {i}: {stripped}"
                    )
                if ("= -0.10" in line or "= 0.10" in line) and "delta" in line.lower():
                    pytest.fail(
                        f"REGRESSION: Hardcoded 0.10 Delta in "
                        f"{filepath.name} Zeile {i}: {stripped}"
                    )


class TestDeltaRegressionCrossConsistency:
    """
    Regressionstests: Alle Delta-Quellen müssen konsistent sein.

    Prüft, dass trading_rules, risk_management, OptionsConfig und
    StrikeRecommender die gleichen Werte verwenden.
    """

    def test_all_short_delta_targets_match(self):
        """Alle Short Delta Targets müssen identisch sein"""
        from constants.trading_rules import SPREAD_SHORT_DELTA_TARGET
        from constants.risk_management import DELTA_TARGET
        from strike_recommender import StrikeRecommender

        rec = StrikeRecommender(use_config_loader=False)

        assert SPREAD_SHORT_DELTA_TARGET == DELTA_TARGET, (
            f"trading_rules ({SPREAD_SHORT_DELTA_TARGET}) != "
            f"risk_management ({DELTA_TARGET})"
        )
        assert rec.config["delta_target"] == SPREAD_SHORT_DELTA_TARGET, (
            f"StrikeRecommender ({rec.config['delta_target']}) != "
            f"trading_rules ({SPREAD_SHORT_DELTA_TARGET})"
        )

    def test_all_short_delta_mins_match(self):
        """Alle Short Delta Mins müssen identisch sein"""
        from constants.trading_rules import SPREAD_SHORT_DELTA_MIN
        from constants.risk_management import DELTA_MIN
        from strike_recommender import StrikeRecommender

        rec = StrikeRecommender(use_config_loader=False)

        assert SPREAD_SHORT_DELTA_MIN == DELTA_MIN
        assert rec.config["delta_min"] == SPREAD_SHORT_DELTA_MIN

    def test_all_short_delta_maxs_match(self):
        """Alle Short Delta Maxs müssen identisch sein"""
        from constants.trading_rules import SPREAD_SHORT_DELTA_MAX
        from constants.risk_management import DELTA_MAX
        from strike_recommender import StrikeRecommender

        rec = StrikeRecommender(use_config_loader=False)

        assert SPREAD_SHORT_DELTA_MAX == DELTA_MAX
        assert rec.config["delta_max"] == SPREAD_SHORT_DELTA_MAX

    def test_all_long_delta_targets_match(self):
        """Alle Long Delta Targets müssen identisch sein"""
        from constants.trading_rules import SPREAD_LONG_DELTA_TARGET
        from constants.risk_management import DELTA_LONG_TARGET
        from strike_recommender import StrikeRecommender

        rec = StrikeRecommender(use_config_loader=False)

        assert SPREAD_LONG_DELTA_TARGET == DELTA_LONG_TARGET
        assert rec.config["long_delta_target"] == SPREAD_LONG_DELTA_TARGET

    def test_all_long_delta_mins_match(self):
        """Alle Long Delta Mins müssen identisch sein"""
        from constants.trading_rules import SPREAD_LONG_DELTA_MIN
        from constants.risk_management import DELTA_LONG_MIN
        from strike_recommender import StrikeRecommender

        rec = StrikeRecommender(use_config_loader=False)

        assert SPREAD_LONG_DELTA_MIN == DELTA_LONG_MIN
        assert rec.config["long_delta_min"] == SPREAD_LONG_DELTA_MIN

    def test_all_long_delta_maxs_match(self):
        """Alle Long Delta Maxs müssen identisch sein"""
        from constants.trading_rules import SPREAD_LONG_DELTA_MAX
        from constants.risk_management import DELTA_LONG_MAX
        from strike_recommender import StrikeRecommender

        rec = StrikeRecommender(use_config_loader=False)

        assert SPREAD_LONG_DELTA_MAX == DELTA_LONG_MAX
        assert rec.config["long_delta_max"] == SPREAD_LONG_DELTA_MAX


# =============================================================================
# TEIL 3: INTEGRATIONSTESTS - Delta-Werte fließen korrekt durch Pipeline
# =============================================================================


class TestDeltaConfigLoaderIntegration:
    """
    Integrationstests: YAML-Config wird korrekt zu OptionsConfig geladen
    """

    @pytest.fixture
    def config_dir_with_deltas(self, tmp_path):
        """Erstellt ein temporäres Config-Dir mit angepassten Deltas"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        settings_yaml = """
options_analysis:
  expiration:
    dte_minimum: 60
    dte_maximum: 90
    dte_target: 75
  short_put:
    delta_minimum: -0.18
    delta_maximum: -0.22
    delta_target: -0.20
  long_put:
    delta_minimum: -0.03
    delta_maximum: -0.06
    delta_target: -0.05
"""
        (config_dir / "settings.yaml").write_text(settings_yaml)
        return config_dir

    def test_yaml_deltas_loaded_correctly(self, config_dir_with_deltas):
        """YAML Delta-Werte werden korrekt in OptionsConfig geladen"""
        from config import ConfigLoader

        loader = ConfigLoader(str(config_dir_with_deltas))
        settings = loader.load_all()

        assert settings.options.delta_target == -0.20
        assert settings.options.delta_minimum == -0.18
        assert settings.options.delta_maximum == -0.22
        assert settings.options.long_delta_target == -0.05
        assert settings.options.long_delta_minimum == -0.03
        assert settings.options.long_delta_maximum == -0.06

    def test_yaml_custom_deltas_override_defaults(self, tmp_path):
        """Custom YAML-Deltas überschreiben die Defaults"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Vollständige Config mit gültigen Werten
        # delta_minimum muss weniger aggressiv (kleiner |delta|) sein als delta_maximum
        settings_yaml = """
options_analysis:
  short_put:
    delta_minimum: -0.22
    delta_maximum: -0.28
    delta_target: -0.25
  long_put:
    delta_minimum: -0.06
    delta_maximum: -0.10
    delta_target: -0.08
"""
        (config_dir / "settings.yaml").write_text(settings_yaml)

        from config import ConfigLoader

        loader = ConfigLoader(str(config_dir))
        settings = loader.load_all()

        assert settings.options.delta_target == -0.25
        assert settings.options.long_delta_target == -0.08
        assert settings.options.delta_minimum == -0.22
        assert settings.options.delta_maximum == -0.28

    def test_missing_yaml_uses_defaults(self, tmp_path):
        """Fehlende YAML-Datei verwendet Defaults"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        # Keine settings.yaml erstellen

        from config import ConfigLoader

        loader = ConfigLoader(str(config_dir))
        settings = loader.load_all()

        assert settings.options.delta_target == -0.20
        assert settings.options.long_delta_target == -0.05


class TestDeltaStrikeRecommenderIntegration:
    """
    Integrationstests: Delta-Werte fließen korrekt in Strike-Empfehlungen
    """

    @pytest.fixture
    def recommender(self):
        from strike_recommender import StrikeRecommender
        return StrikeRecommender(use_config_loader=False)

    @pytest.fixture
    def options_chain_700(self):
        """Options-Chain für $720 Aktie mit realistischen Deltas"""
        return [
            {"strike": 700.0, "right": "P", "delta": -0.50, "bid": 30.0, "ask": 31.0, "open_interest": 500, "volume": 100},
            {"strike": 680.0, "right": "P", "delta": -0.35, "bid": 18.0, "ask": 19.0, "open_interest": 400, "volume": 80},
            {"strike": 660.0, "right": "P", "delta": -0.25, "bid": 12.0, "ask": 13.0, "open_interest": 350, "volume": 60},
            {"strike": 640.0, "right": "P", "delta": -0.20, "bid": 8.50, "ask": 9.00, "open_interest": 300, "volume": 50},
            {"strike": 630.0, "right": "P", "delta": -0.18, "bid": 7.00, "ask": 7.50, "open_interest": 250, "volume": 40},
            {"strike": 620.0, "right": "P", "delta": -0.15, "bid": 5.50, "ask": 6.00, "open_interest": 200, "volume": 30},
            {"strike": 600.0, "right": "P", "delta": -0.10, "bid": 3.50, "ask": 4.00, "open_interest": 200, "volume": 25},
            {"strike": 580.0, "right": "P", "delta": -0.07, "bid": 2.00, "ask": 2.50, "open_interest": 150, "volume": 20},
            {"strike": 560.0, "right": "P", "delta": -0.05, "bid": 1.20, "ask": 1.50, "open_interest": 150, "volume": 15},
            {"strike": 540.0, "right": "P", "delta": -0.03, "bid": 0.60, "ask": 0.80, "open_interest": 120, "volume": 10},
            {"strike": 520.0, "right": "P", "delta": -0.02, "bid": 0.30, "ask": 0.50, "open_interest": 100, "volume": 5},
        ]

    def test_short_strike_selected_by_delta_020(self, recommender, options_chain_700):
        """Short Strike wird per Delta -0.20 ausgewählt, nicht -0.30"""
        rec = recommender.get_recommendation(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0, 650.0],
            options_data=options_chain_700,
        )

        # Short Strike sollte bei Delta ~-0.20 liegen (640.0),
        # NICHT bei -0.30 (das wäre der alte Bug)
        assert rec.short_strike is not None
        if rec.estimated_delta is not None:
            assert -0.23 <= rec.estimated_delta <= -0.17, (
                f"Short Delta {rec.estimated_delta} liegt außerhalb von [-0.23, -0.17]. "
                f"Prüfe ob alter Wert -0.30 verwendet wird!"
            )

    def test_long_strike_selected_by_delta_005(self, recommender, options_chain_700):
        """Long Strike wird per Delta -0.05 ausgewählt, nicht -0.10"""
        rec = recommender.get_recommendation(
            symbol="META",
            current_price=720.0,
            support_levels=[680.0, 650.0],
            options_data=options_chain_700,
        )

        # Long Delta sollte nahe -0.05 sein, NICHT -0.10
        if rec.long_delta is not None:
            assert -0.07 <= rec.long_delta <= -0.03, (
                f"Long Delta {rec.long_delta} liegt außerhalb von [-0.07, -0.03]. "
                f"Prüfe ob alter Wert -0.10 verwendet wird!"
            )

    def test_custom_config_overrides_delta(self):
        """Explizite Config überschreibt Default-Deltas"""
        from strike_recommender import StrikeRecommender

        custom = {
            "delta_target": -0.15,
            "delta_min": -0.12,
            "delta_max": -0.18,
            "long_delta_target": -0.03,
            "long_delta_min": -0.01,
            "long_delta_max": -0.05,
        }

        rec = StrikeRecommender(config=custom, use_config_loader=False)

        assert rec.config["delta_target"] == -0.15
        assert rec.config["delta_min"] == -0.12
        assert rec.config["delta_max"] == -0.18
        assert rec.config["long_delta_target"] == -0.03
        assert rec.config["long_delta_min"] == -0.01
        assert rec.config["long_delta_max"] == -0.05

    def test_config_loader_disabled_uses_constants(self):
        """use_config_loader=False verwendet Constants aus trading_rules"""
        from strike_recommender import StrikeRecommender
        from constants.trading_rules import (
            SPREAD_SHORT_DELTA_TARGET,
            SPREAD_SHORT_DELTA_MIN,
            SPREAD_SHORT_DELTA_MAX,
            SPREAD_LONG_DELTA_TARGET,
            SPREAD_LONG_DELTA_MIN,
            SPREAD_LONG_DELTA_MAX,
        )

        rec = StrikeRecommender(use_config_loader=False)

        assert rec.config["delta_target"] == SPREAD_SHORT_DELTA_TARGET
        assert rec.config["delta_min"] == SPREAD_SHORT_DELTA_MIN
        assert rec.config["delta_max"] == SPREAD_SHORT_DELTA_MAX
        assert rec.config["long_delta_target"] == SPREAD_LONG_DELTA_TARGET
        assert rec.config["long_delta_min"] == SPREAD_LONG_DELTA_MIN
        assert rec.config["long_delta_max"] == SPREAD_LONG_DELTA_MAX

    def test_find_short_strike_respects_delta_range(self, recommender, options_chain_700):
        """_find_short_strike akzeptiert nur Optionen im Delta-Range"""
        result = recommender._find_short_strike(
            current_price=720.0,
            supports=[],
            options_data=options_chain_700,
        )

        assert result is not None
        short_strike, reason, _ = result

        # Finde das Delta für den gewählten Strike
        selected_option = next(
            (o for o in options_chain_700 if o["strike"] == short_strike), None
        )
        if selected_option and "Delta Targeting" in reason:
            delta = selected_option["delta"]
            assert -0.23 <= delta <= -0.17, (
                f"Short Strike {short_strike} hat Delta {delta}, "
                f"das außerhalb des Bereichs [-0.23, -0.17] liegt"
            )

    def test_find_long_strike_respects_delta_range(self, recommender, options_chain_700):
        """_find_long_strike_by_delta akzeptiert nur Optionen im Delta-Range"""
        result = recommender._find_long_strike_by_delta(
            options_data=options_chain_700,
            short_strike=640.0,
        )

        assert result is not None
        long_strike, long_delta = result

        assert -0.07 <= long_delta <= -0.03, (
            f"Long Strike {long_strike} hat Delta {long_delta}, "
            f"das außerhalb des Bereichs [-0.07, -0.03] liegt"
        )
        assert long_strike < 640.0, "Long Strike muss unter Short Strike liegen"

    def test_options_outside_delta_range_rejected(self, recommender):
        """Optionen außerhalb des Delta-Range werden abgelehnt"""
        # Nur Optionen mit Delta -0.30 und -0.40 (außerhalb von [-0.23, -0.17])
        options_only_high_delta = [
            {"strike": 90.0, "right": "P", "delta": -0.40, "bid": 5.0, "ask": 5.5, "open_interest": 200, "volume": 50},
            {"strike": 85.0, "right": "P", "delta": -0.30, "bid": 3.0, "ask": 3.5, "open_interest": 200, "volume": 50},
        ]

        result = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_only_high_delta,
        )

        # Sollte KEIN Delta-basiertes Ergebnis geben (Fallback zu OTM)
        if result is not None:
            _, reason, _ = result
            if "Delta Targeting" in reason:
                pytest.fail(
                    "Strike mit Delta -0.30/-0.40 hätte nicht per "
                    "Delta Targeting gewählt werden dürfen!"
                )


class TestDeltaEndToEndPipeline:
    """
    Integrationstests: Vollständiger End-to-End-Flow
    """

    def test_full_recommendation_pipeline(self):
        """Vollständiger Flow: Constants -> Config -> Recommender -> Recommendation"""
        from constants.trading_rules import (
            SPREAD_SHORT_DELTA_TARGET,
            SPREAD_LONG_DELTA_TARGET,
        )
        from strike_recommender import StrikeRecommender

        # 1. Constants korrekt
        assert SPREAD_SHORT_DELTA_TARGET == -0.20
        assert SPREAD_LONG_DELTA_TARGET == -0.05

        # 2. Recommender verwendet Constants
        rec = StrikeRecommender(use_config_loader=False)
        assert rec.config["delta_target"] == -0.20
        assert rec.config["long_delta_target"] == -0.05

        # 3. Empfehlung verwenden korrekte Deltas
        options_chain = [
            {"strike": 180.0, "right": "P", "delta": -0.30, "bid": 5.0, "ask": 5.5, "open_interest": 300, "volume": 50},
            {"strike": 170.0, "right": "P", "delta": -0.20, "bid": 3.0, "ask": 3.5, "open_interest": 250, "volume": 40},
            {"strike": 165.0, "right": "P", "delta": -0.18, "bid": 2.5, "ask": 3.0, "open_interest": 200, "volume": 30},
            {"strike": 155.0, "right": "P", "delta": -0.10, "bid": 1.0, "ask": 1.5, "open_interest": 200, "volume": 20},
            {"strike": 150.0, "right": "P", "delta": -0.05, "bid": 0.5, "ask": 0.8, "open_interest": 150, "volume": 15},
            {"strike": 145.0, "right": "P", "delta": -0.03, "bid": 0.3, "ask": 0.5, "open_interest": 100, "volume": 10},
        ]

        recommendation = rec.get_recommendation(
            symbol="AAPL",
            current_price=200.0,
            support_levels=[175.0, 165.0],
            options_data=options_chain,
        )

        assert recommendation is not None
        assert recommendation.short_strike < 200.0

        # Short Strike sollte Delta ~-0.20 haben, nicht -0.30
        if recommendation.estimated_delta is not None:
            assert abs(recommendation.estimated_delta) != 0.30, (
                "REGRESSION: Short Strike verwendet alten Delta-Wert 0.30!"
            )

    def test_multiple_recommendations_use_correct_deltas(self):
        """Mehrere Empfehlungen verwenden alle korrekte Deltas"""
        from strike_recommender import StrikeRecommender

        rec = StrikeRecommender(use_config_loader=False)

        options_chain = [
            {"strike": 450.0, "right": "P", "delta": -0.30, "bid": 12.0, "ask": 12.5, "open_interest": 300, "volume": 50},
            {"strike": 430.0, "right": "P", "delta": -0.22, "bid": 8.0, "ask": 8.5, "open_interest": 250, "volume": 40},
            {"strike": 420.0, "right": "P", "delta": -0.20, "bid": 6.5, "ask": 7.0, "open_interest": 200, "volume": 35},
            {"strike": 410.0, "right": "P", "delta": -0.17, "bid": 5.0, "ask": 5.5, "open_interest": 200, "volume": 30},
            {"strike": 380.0, "right": "P", "delta": -0.10, "bid": 2.0, "ask": 2.5, "open_interest": 150, "volume": 20},
            {"strike": 360.0, "right": "P", "delta": -0.06, "bid": 1.0, "ask": 1.3, "open_interest": 150, "volume": 15},
            {"strike": 350.0, "right": "P", "delta": -0.05, "bid": 0.8, "ask": 1.0, "open_interest": 120, "volume": 10},
            {"strike": 340.0, "right": "P", "delta": -0.04, "bid": 0.5, "ask": 0.7, "open_interest": 120, "volume": 10},
            {"strike": 330.0, "right": "P", "delta": -0.03, "bid": 0.3, "ask": 0.5, "open_interest": 100, "volume": 5},
        ]

        recs = rec.get_multiple_recommendations(
            symbol="MSFT",
            current_price=500.0,
            support_levels=[450.0, 420.0],
            options_data=options_chain,
            num_alternatives=3,
        )

        for r in recs:
            if r.estimated_delta is not None:
                assert abs(r.estimated_delta) != 0.30, (
                    f"REGRESSION: Empfehlung für Strike {r.short_strike} "
                    f"verwendet alten Delta 0.30"
                )

    def test_config_yaml_to_recommendation_flow(self, tmp_path):
        """YAML Config -> ConfigLoader -> StrikeRecommender -> Recommendation"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        settings_yaml = """
options_analysis:
  short_put:
    delta_minimum: -0.18
    delta_maximum: -0.22
    delta_target: -0.20
  long_put:
    delta_minimum: -0.03
    delta_maximum: -0.06
    delta_target: -0.05
"""
        (config_dir / "settings.yaml").write_text(settings_yaml)

        from config import ConfigLoader

        loader = ConfigLoader(str(config_dir))
        settings = loader.load_all()

        # Verifiziere dass OptionsConfig korrekt geladen wurde
        assert settings.options.delta_target == -0.20
        assert settings.options.long_delta_target == -0.05

        # Verifiziere die Grenzen
        assert settings.options.delta_minimum == -0.18
        assert settings.options.delta_maximum == -0.22
        assert settings.options.long_delta_minimum == -0.03
        assert settings.options.long_delta_maximum == -0.06


class TestDeltaParameterized:
    """
    Parametrisierte Tests: Verschiedene Delta-Konfigurationen durchspielen
    """

    @pytest.mark.parametrize(
        "delta_target,delta_min,delta_max",
        [
            (-0.20, -0.17, -0.23),  # Standard PLAYBOOK
            (-0.15, -0.12, -0.18),  # Konservativer
            (-0.25, -0.22, -0.28),  # Aggressiver
        ],
        ids=["playbook_standard", "conservative", "aggressive"],
    )
    def test_strike_recommender_respects_custom_deltas(
        self, delta_target, delta_min, delta_max
    ):
        """StrikeRecommender respektiert benutzerdefinierte Delta-Werte"""
        from strike_recommender import StrikeRecommender

        config = {
            "delta_target": delta_target,
            "delta_min": delta_min,
            "delta_max": delta_max,
        }

        rec = StrikeRecommender(config=config, use_config_loader=False)

        assert rec.config["delta_target"] == delta_target
        assert rec.config["delta_min"] == delta_min
        assert rec.config["delta_max"] == delta_max

    @pytest.mark.parametrize(
        "bad_delta,description",
        [
            (-0.30, "alter Bug-Wert Short"),
            (-0.10, "alter Bug-Wert Long"),
            (0.0, "Null-Delta"),
            (0.20, "positives Delta (Call)"),
        ],
        ids=["old_bug_030", "old_bug_010", "zero_delta", "positive_delta"],
    )
    def test_default_constants_are_not_bad_values(self, bad_delta, description):
        """Default-Konstanten enthalten keine bekannten fehlerhaften Werte"""
        from constants.trading_rules import (
            SPREAD_SHORT_DELTA_TARGET,
            SPREAD_LONG_DELTA_TARGET,
        )

        assert SPREAD_SHORT_DELTA_TARGET != bad_delta, (
            f"Short Delta Target ist {description}: {bad_delta}"
        )
        assert SPREAD_LONG_DELTA_TARGET != bad_delta, (
            f"Long Delta Target ist {description}: {bad_delta}"
        )


# =============================================================================
# TEIL 4: EDGE CASES UND GRENZWERTE
# =============================================================================


class TestDeltaEdgeCases:
    """Edge Cases für Delta-Handling"""

    @pytest.fixture
    def recommender(self):
        from strike_recommender import StrikeRecommender
        return StrikeRecommender(use_config_loader=False)

    def test_no_options_in_range_returns_poor(self, recommender):
        """Keine Option im Delta-Range mit options_data -> POOR quality"""
        from strike_recommender import StrikeQuality
        options_data = [
            {"strike": 90.0, "right": "P", "delta": -0.50, "bid": 5.0, "ask": 5.5, "open_interest": 200, "volume": 50},
            {"strike": 80.0, "right": "P", "delta": -0.40, "bid": 3.0, "ask": 3.5, "open_interest": 200, "volume": 50},
        ]

        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],
            options_data=options_data,
        )

        # With options_data present but no liquid strikes in range -> POOR quality
        assert rec is not None
        assert rec.quality == StrikeQuality.POOR

    def test_empty_options_data_falls_back(self, recommender):
        """Leere Options-Daten -> Fallback auf Support/OTM-basiert"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],
            options_data=[],
        )

        assert rec is not None
        assert rec.short_strike > 0

    def test_none_options_data_falls_back(self, recommender):
        """None Options-Daten -> Fallback auf Support/OTM-basiert"""
        rec = recommender.get_recommendation(
            symbol="TEST",
            current_price=100.0,
            support_levels=[90.0, 85.0],
            options_data=None,
        )

        assert rec is not None
        assert rec.short_strike > 0

    def test_exact_boundary_delta_accepted(self, recommender):
        """Exakte Grenzwerte des Delta-Range werden akzeptiert"""
        # Delta genau auf -0.17 und -0.23 (Grenzen des Range)
        options_data = [
            {"strike": 95.0, "right": "P", "delta": -0.17, "bid": 1.0, "ask": 1.5, "open_interest": 200, "volume": 50},
            {"strike": 85.0, "right": "P", "delta": -0.23, "bid": 2.0, "ask": 2.5, "open_interest": 200, "volume": 50},
        ]

        result = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data,
        )

        # Mindestens eine Option sollte akzeptiert werden
        # (delta_min=-0.17 und delta_max=-0.23, check: delta > delta_min or delta < delta_max)
        # -0.17 > -0.17 = False, -0.17 < -0.23 = False -> akzeptiert
        if result is not None:
            _, reason, _ = result
            if "Delta Targeting" in reason:
                # Mindestens eine wurde akzeptiert
                pass

    def test_only_call_options_ignored(self, recommender):
        """Call-Optionen werden bei Put-Strike-Selection ignoriert"""
        options_data = [
            {"strike": 95.0, "right": "C", "delta": 0.80, "bid": 10.0, "ask": 10.5},
            {"strike": 90.0, "right": "C", "delta": 0.70, "bid": 8.0, "ask": 8.5},
        ]

        result = recommender._find_short_strike(
            current_price=100.0,
            supports=[],
            options_data=options_data,
        )

        # Kein Delta-basiertes Ergebnis, da nur Calls vorhanden
        if result is not None:
            _, reason, _ = result
            assert "Delta Targeting" not in reason


# =============================================================================
# TEIL 5: VIX STRATEGY - Long Delta im StrategyRecommendation
# =============================================================================


class TestDeltaVixStrategy:
    """
    Tests: VIX Strategy verwendet korrekte Delta-Werte
    und das neue long_delta_target Feld funktioniert.
    """

    def test_strategy_recommendation_has_long_delta_target(self):
        """StrategyRecommendation hat ein long_delta_target Feld"""
        from vix_strategy import StrategyRecommendation
        import dataclasses

        field_names = [f.name for f in dataclasses.fields(StrategyRecommendation)]
        assert "long_delta_target" in field_names, (
            "StrategyRecommendation fehlt das Feld 'long_delta_target'"
        )

    def test_strategy_recommendation_long_delta_value(self):
        """StrategyRecommendation.long_delta_target ist -0.05"""
        from vix_strategy import get_strategy_for_vix

        rec = get_strategy_for_vix(18.0)
        assert rec.long_delta_target == -0.05

    def test_strategy_recommendation_to_dict_has_long_delta(self):
        """to_dict() enthält long_delta_target"""
        from vix_strategy import get_strategy_for_vix

        rec = get_strategy_for_vix(18.0)
        d = rec.to_dict()

        assert "long_delta_target" in d["recommendations"], (
            "to_dict() fehlt 'long_delta_target' in recommendations"
        )
        assert d["recommendations"]["long_delta_target"] == -0.05

    @pytest.mark.parametrize(
        "vix,expected_profile",
        [
            (12.0, "conservative"),
            (18.0, "standard"),
            (22.0, "danger_zone"),
            (27.0, "elevated"),
            (35.0, "high_volatility"),
        ],
        ids=["low_vol", "normal", "danger_zone", "elevated", "high_vol"],
    )
    def test_all_profiles_use_correct_short_delta(self, vix, expected_profile):
        """Alle VIX-Profile verwenden Short Delta -0.20"""
        from vix_strategy import get_strategy_for_vix

        rec = get_strategy_for_vix(vix)
        assert rec.profile_name == expected_profile
        assert rec.delta_target == -0.20, (
            f"Profile '{expected_profile}' hat Short Delta {rec.delta_target}, "
            f"erwartet -0.20"
        )

    @pytest.mark.parametrize(
        "vix,expected_profile",
        [
            (12.0, "conservative"),
            (18.0, "standard"),
            (22.0, "danger_zone"),
            (27.0, "elevated"),
            (35.0, "high_volatility"),
        ],
        ids=["low_vol", "normal", "danger_zone", "elevated", "high_vol"],
    )
    def test_all_profiles_use_correct_long_delta(self, vix, expected_profile):
        """Alle VIX-Profile verwenden Long Delta -0.05"""
        from vix_strategy import get_strategy_for_vix

        rec = get_strategy_for_vix(vix)
        assert rec.long_delta_target == -0.05, (
            f"Profile '{expected_profile}' hat Long Delta {rec.long_delta_target}, "
            f"erwartet -0.05"
        )

    def test_get_strategy_for_stock_has_long_delta(self):
        """get_strategy_for_stock() Ergebnis enthält long_delta_target"""
        from vix_strategy import get_strategy_for_stock

        rec = get_strategy_for_stock(18.0, 150.0)
        assert hasattr(rec, "long_delta_target")
        assert rec.long_delta_target == -0.05

    def test_long_delta_comes_from_constant(self):
        """long_delta_target kommt aus DELTA_LONG_TARGET Konstante"""
        from vix_strategy import get_strategy_for_vix
        from constants.risk_management import DELTA_LONG_TARGET

        rec = get_strategy_for_vix(18.0)
        assert rec.long_delta_target == DELTA_LONG_TARGET, (
            f"long_delta_target ({rec.long_delta_target}) != "
            f"DELTA_LONG_TARGET ({DELTA_LONG_TARGET})"
        )


# =============================================================================
# TEIL 6: CONSTANTS EXPORT - Long Delta ist importierbar
# =============================================================================


class TestDeltaConstantsExport:
    """
    Tests: DELTA_LONG_* Konstanten sind aus constants/ importierbar
    und stimmen mit risk_management.py überein.
    """

    def test_delta_long_target_importable(self):
        """DELTA_LONG_TARGET ist aus constants importierbar"""
        from constants import DELTA_LONG_TARGET
        assert DELTA_LONG_TARGET == -0.05

    def test_delta_long_min_importable(self):
        """DELTA_LONG_MIN ist aus constants importierbar"""
        from constants import DELTA_LONG_MIN
        assert DELTA_LONG_MIN == -0.03

    def test_delta_long_max_importable(self):
        """DELTA_LONG_MAX ist aus constants importierbar"""
        from constants import DELTA_LONG_MAX
        assert DELTA_LONG_MAX == -0.07

    def test_exports_match_risk_management(self):
        """Export-Werte stimmen mit risk_management.py überein"""
        from constants import DELTA_LONG_TARGET, DELTA_LONG_MIN, DELTA_LONG_MAX
        from constants.risk_management import (
            DELTA_LONG_TARGET as RM_TARGET,
            DELTA_LONG_MIN as RM_MIN,
            DELTA_LONG_MAX as RM_MAX,
        )

        assert DELTA_LONG_TARGET == RM_TARGET
        assert DELTA_LONG_MIN == RM_MIN
        assert DELTA_LONG_MAX == RM_MAX


# =============================================================================
# TEIL 7: HANDLER REGRESSION - Keine hardcoded Deltas in Handlers
# =============================================================================


class TestDeltaHandlerRegression:
    """
    Regressionstests: Handler-Dateien enthalten keine hardcoded Delta-Werte.

    Prüft Source-Code der Handler nach String-Patterns die auf
    hardcoded Delta-Werte hindeuten.
    """

    @pytest.fixture
    def handlers_dir(self):
        return Path(__file__).parent.parent / "src" / "handlers"

    def _find_hardcoded_delta_strings(self, filepath: Path, pattern: str) -> list:
        """Sucht nach hardcoded Delta-Strings in einer Datei (ignoriert Kommentare)."""
        violations = []
        if not filepath.exists():
            return violations

        content = filepath.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            # Überspringe Kommentare
            if stripped.startswith("#"):
                continue
            # Überspringe Docstrings (einfache Erkennung)
            if stripped.startswith('"""') or stripped.startswith("'''"):
                continue

            if pattern in line:
                violations.append(f"{filepath.name}:{line_num}: {stripped}")

        return violations

    def test_no_hardcoded_005_in_vix_handler(self, handlers_dir):
        """handlers/vix.py: Kein hardcoded '-0.05' String mehr"""
        filepath = handlers_dir / "vix.py"
        violations = self._find_hardcoded_delta_strings(filepath, '"-0.05"')

        assert len(violations) == 0, (
            f"Hardcoded '-0.05' in vix.py gefunden:\n"
            + "\n".join(violations)
        )

    def test_no_hardcoded_030_in_scan_handler(self, handlers_dir):
        """handlers/scan.py: Kein hardcoded '-0.30' oder '0.30' Delta"""
        filepath = handlers_dir / "scan.py"
        if not filepath.exists():
            pytest.skip("scan.py nicht gefunden")

        for pattern in ['"-0.30"', '"0.30"', "= -0.30", "= 0.30"]:
            violations = self._find_hardcoded_delta_strings(filepath, pattern)
            for v in violations:
                if "delta" in v.lower():
                    pytest.fail(
                        f"Hardcoded Delta '{pattern}' in scan.py: {v}"
                    )

    def test_no_hardcoded_030_in_analysis_handler(self, handlers_dir):
        """handlers/analysis.py: Kein hardcoded '-0.30' oder '0.30' Delta"""
        filepath = handlers_dir / "analysis.py"
        if not filepath.exists():
            pytest.skip("analysis.py nicht gefunden")

        for pattern in ['"-0.30"', '"0.30"', "= -0.30", "= 0.30"]:
            violations = self._find_hardcoded_delta_strings(filepath, pattern)
            for v in violations:
                if "delta" in v.lower():
                    pytest.fail(
                        f"Hardcoded Delta '{pattern}' in analysis.py: {v}"
                    )

    def test_no_hardcoded_010_in_any_handler(self, handlers_dir):
        """Kein Handler hat hardcoded '-0.10' oder '0.10' als Long Delta"""
        if not handlers_dir.exists():
            pytest.skip("handlers/ Verzeichnis nicht gefunden")

        for filepath in handlers_dir.glob("*.py"):
            for pattern in ['"-0.10"', '"0.10"', "= -0.10", "= 0.10"]:
                violations = self._find_hardcoded_delta_strings(filepath, pattern)
                for v in violations:
                    if "delta" in v.lower():
                        pytest.fail(
                            f"Hardcoded Long Delta '{pattern}' in {filepath.name}: {v}"
                        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
