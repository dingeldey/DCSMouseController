import re

class IniReader:
    def __init__(self, path):
        import configparser
        self.cfg = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
        self.cfg.optionxform = str  # preserve case
        self.cfg.read(path, encoding="utf-8")

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
        try:
            return int(self.get_str(section, option, str(fallback)))
        except ValueError:
            return fallback

    def get_float(self, section: str, option: str, fallback: float = 0.0) -> float:
        try:
            return float(self.get_str(section, option, str(fallback)))
        except ValueError:
            return fallback

    def get_bool(self, section: str, option: str, fallback: bool = False) -> bool:
        val = self.get_str(section, option, str(fallback))
        return val.lower() in ("1", "yes", "true", "on")

    def get_list(self, section: str, option: str):
        if not self.cfg.has_option(section, option):
            return []
        raw = self.cfg.get(section, option, fallback="")

        # Handle line continuations like "\" in INI
        joined = raw.replace("\\\n", " ").replace("\\", " ")

        # Split only on commas that are NOT inside brackets
        tokens = re.split(r",(?![^\[]*\])", joined)

        return [t.strip() for t in tokens if t.strip()]

