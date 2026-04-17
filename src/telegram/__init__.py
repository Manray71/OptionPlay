"""OptionPlay Telegram Bot.

Push-based scanner notifications with inline buttons for shadow-trade logging.

Components:
  - notifier: DailyPick -> Telegram message formatting
  - bot: Application setup, command handlers, callback handlers
  - scheduler: APScheduler integration, 3 daily scan jobs

Configuration: config/telegram.yaml + .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
"""

import sys as _sys
from pathlib import Path as _Path


def _bootstrap_real_ptb() -> None:
    """Ensure sys.modules['telegram'] points to the real python-telegram-bot.

    When src/ is prepended to sys.path (e.g. by conftest.py), Python finds
    src/telegram/ when resolving 'telegram', shadowing the installed library.
    This function runs at the top of src/telegram/__init__.py — before any
    submodule that needs InlineKeyboardButton — and replaces the shadow with
    the real package.  It does NOT restore the shadow afterward: callers who
    import 'telegram' should get the real ptb, not our internal package.
    """
    src_dir = str(_Path(__file__).resolve().parent.parent)  # .../OptionPlay/src

    current = _sys.modules.get("telegram")
    if current is not None and getattr(current, "__file__", None) != __file__:
        return  # real ptb already loaded

    # Find real telegram in site-packages (skip any entry that resolves to src/)
    src_path_obj = _Path(src_dir)
    for entry in _sys.path:
        norm = _Path(entry).resolve()
        if norm == src_path_obj:
            continue
        if (norm / "telegram" / "__init__.py").exists():
            # Temporarily remove ALL sys.path entries that resolve to src_dir
            # (conftest may insert a relative "src" or an absolute path — remove both).
            shadow = _sys.modules.pop("telegram", None)
            removed_entries = []
            for _e in list(_sys.path):
                if _Path(_e).resolve() == src_path_obj:
                    _sys.path.remove(_e)
                    removed_entries.append(_e)
            # Clear PathFinder's importer cache — it caches finders for each
            # sys.path entry and persists even after sys.path.remove().
            import importlib as _il
            for _e in removed_entries:
                _sys.path_importer_cache.pop(_e, None)
            _sys.path_importer_cache.pop(src_dir, None)
            _il.invalidate_caches()
            try:
                import telegram  # noqa: F401  (real ptb lands in sys.modules)
            except Exception:
                # Restore on failure so nothing is left broken
                if shadow is not None:
                    _sys.modules["telegram"] = shadow
            finally:
                for _e in removed_entries:
                    _sys.path.insert(0, _e)
            return


_bootstrap_real_ptb()
del _bootstrap_real_ptb

from .notifier import (  # noqa: E402
    format_later_confirmation,
    format_no_picks_message,
    format_pick_buttons,
    format_pick_message,
    format_scan_summary,
    format_shadow_confirmation,
    format_skip_confirmation,
    format_status_message,
    format_vix_message,
)

__all__ = [
    "format_pick_message",
    "format_pick_buttons",
    "format_scan_summary",
    "format_no_picks_message",
    "format_shadow_confirmation",
    "format_skip_confirmation",
    "format_later_confirmation",
    "format_status_message",
    "format_vix_message",
]
