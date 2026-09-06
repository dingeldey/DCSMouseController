import re

class IniReader:
    def __init__(self, path, log=None):
        import configparser
        self.log = log
        self.path = path
        self.cfg = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
        self.cfg.optionxform = str  # preserve case
        # utf-8-sig: strips a UTF-8 BOM if present (e.g. from Notepad's "UTF-8"
        # save option or PowerShell's Out-File), no-op otherwise.
        read_files = self.cfg.read(path, encoding="utf-8-sig")
        if not read_files:
            message = f"Config file not found or unreadable: {path}"
            if log:
                log.error(f"[INI] {message}")
            raise FileNotFoundError(message)

    def _clean(self, val: str) -> str:
        if val is None:
            return ""
        # cut at first ; or #
        for sep in (";", "#"):
            if sep in val:
                val = val.split(sep, 1)[0]
        return val.strip()

    def get_str(self, section: str, option: str, fallback: str = "") -> str:
        if self.cfg.has_option(section, option):
            raw = self.cfg.get(section, option, fallback=fallback)
            return self._clean(raw)
        return fallback

    def get_int(self, section: str, option: str, fallback: int = 0) -> int:
        if not self.cfg.has_option(section, option):
            return fallback
        raw = self.get_str(section, option, str(fallback))
        try:
            return int(raw)
        except ValueError:
            if self.log:
                self.log.warning(f"[INI] [{section}] {option} = {raw!r} is not a valid integer; using default {fallback}")
            return fallback

    def get_float(self, section: str, option: str, fallback: float = 0.0) -> float:
        if not self.cfg.has_option(section, option):
            return fallback
        raw = self.get_str(section, option, str(fallback))
        try:
            return float(raw)
        except ValueError:
            if self.log:
                self.log.warning(f"[INI] [{section}] {option} = {raw!r} is not a valid number; using default {fallback}")
            return fallback

    def get_bool(self, section: str, option: str, fallback: bool = False) -> bool:
        if not self.cfg.has_option(section, option):
            return fallback
        raw = self.get_str(section, option, str(fallback))
        lowered = raw.lower()
        if lowered in ("1", "yes", "true", "on"):
            return True
        if lowered in ("0", "no", "false", "off"):
            return False
        if self.log:
            self.log.warning(f"[INI] [{section}] {option} = {raw!r} is not a valid boolean; using default {fallback}")
        return fallback

    def get_list(self, section: str, option: str):
        if not self.cfg.has_option(section, option):
            return []
        raw = self.cfg.get(section, option, fallback="")

        # Handle line continuations like "\" in INI
        joined = raw.replace("\\\n", " ").replace("\\", " ")

        # Split only on commas that are NOT inside brackets
        tokens = re.split(r",(?![^\[]*\])", joined)

        return [t.strip() for t in tokens if t.strip()]
