"""Editable, comment-preserving view of the controller INI files.

The runtime's :class:`IniReader` intentionally only reads configuration.  The
GUI needs to write it too, while retaining the large syntax guide and any user
comments around the options it owns.  This module replaces individual options
instead of round-tripping the whole file through ``ConfigParser.write``.
"""

from __future__ import annotations

from dataclasses import dataclass
import configparser
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Iterable


DEVICE_RE = re.compile(r"(?P<prefix>dev:)(?P<device>[^:]+)(?=:(?:button|axis):)", re.I)


@dataclass
class MappingRow:
    category: str
    input: str
    output: str

    @property
    def device(self) -> str:
        match = DEVICE_RE.search(self.input)
        return match.group("device").strip() if match else ""

    @property
    def modified(self) -> bool:
        return self.input.rstrip().endswith(":M")

    @property
    def input_label(self) -> str:
        match = re.search(r":(button|axis):(.+?)(?::M)?$", self.input, re.I)
        if not match:
            return self.input
        kind, number = match.groups()
        return f"{kind.title()} {number}"


def replace_device(input_binding: str, old: str, new: str) -> str:
    """Replace one exact device token in a binding string."""
    return DEVICE_RE.sub(
        lambda match: match.group("prefix") + (new if match.group("device").strip() == old else match.group("device")),
        input_binding,
    )


class ConfigDocument:
    """Read and selectively update one profile without discarding comments."""

    OWNED_OPTIONS = ("modifier", "button_toggle", "key_mappings", "axis_mappings")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.text = self.path.read_text(encoding="utf-8-sig")
        self.newline = "\r\n" if "\r\n" in self.text else "\n"
        self._reload_parser()

    def _reload_parser(self) -> None:
        self.parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), strict=False)
        self.parser.optionxform = str
        self.parser.read_string(self.text)

    def get(self, option: str, fallback: str = "") -> str:
        if not self.parser.has_option("input", option):
            return fallback
        return self.parser.get("input", option, fallback=fallback).strip()

    def get_bool(self, option: str, fallback: bool = False) -> bool:
        raw = self.get(option, str(fallback)).split(":", 1)[0].strip().lower()
        return raw in {"1", "yes", "true", "on"}

    @staticmethod
    def _mapping_entries(raw: str) -> list[tuple[str, str]]:
        joined = raw.replace("\\\n", " ").replace("\\", " ")
        entries = re.split(r",(?![^\[]*\])", joined)
        result = []
        for entry in entries:
            if "=>" not in entry:
                continue
            lhs, rhs = (part.strip() for part in entry.split("=>", 1))
            if lhs and rhs:
                result.append((lhs, rhs))
        return result

    def mappings(self) -> list[MappingRow]:
        rows: list[MappingRow] = []
        for category, option in (("key", "key_mappings"), ("axis", "axis_mappings")):
            rows.extend(MappingRow(category, lhs, rhs) for lhs, rhs in self._mapping_entries(self.get(option)))
        return rows

    def referenced_devices(self, rows: Iterable[MappingRow] | None = None) -> list[str]:
        refs = {row.device for row in (rows if rows is not None else self.mappings()) if row.device}
        for option in ("modifier", "button_toggle"):
            match = DEVICE_RE.search(self.get(option))
            if match:
                refs.add(match.group("device").strip())
        return sorted(refs, key=str.casefold)

    def set_option(self, option: str, value: str) -> None:
        """Replace one option in [input], inserting it when absent."""
        lines = self.text.splitlines(keepends=True)
        section_start = section_end = None
        option_start = None
        section_re = re.compile(r"^\s*\[([^]]+)\]\s*(?:[;#].*)?$")
        option_re = re.compile(rf"^\s*{re.escape(option)}\s*=", re.I)

        for index, line in enumerate(lines):
            plain = line.rstrip("\r\n")
            section_match = section_re.match(plain)
            if section_match:
                if section_start is not None:
                    section_end = index
                    break
                if section_match.group(1).strip().lower() == "input":
                    section_start = index
                continue
            if section_start is not None and option_re.match(plain):
                option_start = index

        if section_start is None:
            suffix = "" if self.text.endswith(("\n", "\r")) else self.newline
            self.text += f"{suffix}[input]{self.newline}{option} = {value}{self.newline}"
            self._reload_parser()
            return
        if section_end is None:
            section_end = len(lines)

        rendered = self._render_option(option, value)
        if option_start is None:
            lines[section_end:section_end] = [rendered]
        else:
            end = option_start + 1
            while end < section_end:
                candidate = lines[end].rstrip("\r\n")
                if candidate and candidate[0].isspace() and not candidate.lstrip().startswith((";", "#")):
                    end += 1
                else:
                    break
            lines[option_start:end] = [rendered]

        self.text = "".join(lines)
        self._reload_parser()

    def _render_option(self, option: str, value: str) -> str:
        if option not in {"key_mappings", "axis_mappings"}:
            return f"{option} = {value}{self.newline}"
        entries = [line.strip() for line in value.splitlines() if line.strip()]
        if not entries:
            return f"{option} = {self.newline}"
        if len(entries) == 1:
            return f"{option} = {entries[0]}{self.newline}"
        continuation = f", \\{self.newline}                "
        return f"{option} = {continuation.join(entries)}{self.newline}"

    def set_mappings(self, rows: Iterable[MappingRow]) -> None:
        grouped = {"key": [], "axis": []}
        for row in rows:
            grouped.setdefault(row.category, []).append(f"{row.input.strip()} => {row.output.strip()}")
        self.set_option("key_mappings", "\n".join(grouped["key"]))
        self.set_option("axis_mappings", "\n".join(grouped["axis"]))

    def remap_device(self, old: str, new: str, rows: list[MappingRow]) -> int:
        changed = 0
        for row in rows:
            updated = replace_device(row.input, old, new)
            if updated != row.input:
                row.input = updated
                changed += 1
        for option in ("modifier", "button_toggle"):
            current = self.get(option)
            updated = replace_device(current, old, new)
            if current and updated != current:
                self.set_option(option, updated)
                changed += 1
        return changed

    def save(self, make_backup: bool = True) -> Path | None:
        backup = None
        if make_backup and self.path.exists():
            backup = self.path.with_suffix(self.path.suffix + ".bak")
            shutil.copy2(self.path, backup)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(self.text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return backup
