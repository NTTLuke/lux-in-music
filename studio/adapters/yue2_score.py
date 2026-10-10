"""Duration inspection and compact arrangements for YuE2's two-voice ABC.

This deliberately accepts a bounded dialect, not arbitrary ABC. Timing is
computed from notes/rests and meter, never from characters or lyric words.
Generated arrangements may shorten instrumental passages; vocal bars, tempo,
the first two bars and final four bars are retained. Supplied scores stay intact.
"""

from dataclasses import dataclass
from fractions import Fraction
import math
import re


class ScoreError(ValueError):
    pass


@dataclass
class Bar:
    vocal: str
    instrumental: str
    section: str


@dataclass
class Score:
    header: list[str]
    bars: list[Bar]
    bpm: int
    seconds_per_bar: float

    @property
    def duration_s(self):
        return len(self.bars) * self.seconds_per_bar

    def text(self):
        lines = self.header[:]
        # Keep the native 1–4 bar groups, avoiding an artificial section break
        # at every bar. Compressed rests are expanded without changing timing.
        section = None
        cursor = 0
        while cursor < len(self.bars):
            bar = self.bars[cursor]
            if bar.section != section:
                if bar.section:
                    lines.append(bar.section)
                section = bar.section
            end = cursor + 1
            while end < min(cursor + 4, len(self.bars)) and self.bars[end].section == section:
                end += 1
            group = self.bars[cursor:end]
            lines.extend(["V: Vocal", "|".join(b.vocal for b in group) + "|",
                          "V: Ins", "|".join(b.instrumental for b in group) + "|"])
            cursor = end
        return "\n".join(lines) + "\n"


def _music(bar):
    return re.sub(r'"[^"\n]*"', '', bar).strip()


def _expand(line, units):
    if not line.endswith("|"):
        raise ScoreError("Score music must end at a bar boundary")
    result = []
    for bar in line[:-1].split("|"):
        rest = re.fullmatch(r"Z([1-4])?", bar.strip())
        if rest:
            result.extend(["Z"] * int(rest[1] or 1))
            continue
        music = _music(bar)
        cursor, duration = 0, 0
        while cursor < len(music):
            if music[cursor].isspace():
                cursor += 1
                continue
            note = re.match(r"(?:\^\^|__|\^|_|=)?[A-Ga-gz][,']*(\d*)(-?)", music[cursor:])
            if not note:
                raise ScoreError("Unsupported score notation; duration cannot be checked safely")
            duration += int(note[1] or 1)
            cursor += len(note[0])
        if duration != units:
            raise ScoreError("Score bar duration does not match its meter")
        result.append(bar.strip())
    if not 1 <= len(result) <= 4:
        raise ScoreError("Expected 1–4 bars per native voice group")
    return result


def inspect(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # T: is nonempty as a line, although its value is blank.
    if len(lines) < 12 or lines[:2] != ["X:1", "T:"]:
        raise ScoreError("Expected a complete native two-voice score")
    meter = re.fullmatch(r"M:(\d+)/(\d+)", lines[2])
    unit = re.fullmatch(r"L:1/(\d+)", lines[3])
    tempo = re.fullmatch(r"Q:1/4=([1-9]\d*)", lines[4])
    if not meter or not unit or not tempo or not all(int(x) > 0 for x in (*meter.groups(), unit[1])):
        raise ScoreError("Unsupported score meter, unit length or tempo")
    if not lines[5].startswith("V: Vocal ") or not lines[6].startswith("V: Ins ") or not lines[7].startswith("K:"):
        raise ScoreError("Expected native Vocal and Ins voice definitions")
    units = Fraction(int(meter[1]) * int(unit[1]), int(meter[2]))
    if units.denominator != 1:
        raise ScoreError("Meter is incompatible with the score unit")
    seconds = float(Fraction(int(meter[1]), int(meter[2])) * 4 * 60 / int(tempo[1]))
    bars, section, cursor = [], "", 8
    while cursor < len(lines):
        if lines[cursor].startswith("%"):
            section = lines[cursor]
            cursor += 1
            continue
        if cursor + 3 >= len(lines) or lines[cursor] != "V: Vocal" or lines[cursor + 2] != "V: Ins":
            raise ScoreError("Unsupported voice group or meter/key change")
        vocal = _expand(lines[cursor + 1], units)
        instrumental = _expand(lines[cursor + 3], units)
        if len(vocal) != len(instrumental):
            raise ScoreError("Score voices have different bar counts")
        bars.extend(Bar(v, i, section) for v, i in zip(vocal, instrumental))
        cursor += 4
    if not bars or any(_music(part).endswith("-") for part in (bars[-1].vocal, bars[-1].instrumental)):
        raise ScoreError("Score has no ending or has an unresolved final tie")
    return Score(lines[:8], bars, int(tempo[1]), seconds)


def fit(text, target_s):
    score = inspect(text)
    original_s = score.duration_s
    limit = math.floor(target_s / score.seconds_per_bar)
    removed = 0
    while len(score.bars) > limit:
        candidates = []
        for index in range(2, len(score.bars) - 4):
            bar = score.bars[index]
            if re.search(r"[A-Ga-g]", _music(bar.vocal)):
                continue
            # Keep breathing rests adjacent to vocal phrases and avoid severing
            # instrumental ties at either edge of a removed bar.
            if any(re.search(r"[A-Ga-g]", _music(score.bars[j].vocal)) for j in (index - 1, index + 1)):
                continue
            if _music(score.bars[index - 1].instrumental).endswith("-"):
                continue
            for end in range(index + 1, min(len(score.bars) - 4, index + len(score.bars) - limit) + 1):
                last = score.bars[end - 1]
                if re.search(r"[A-Ga-g]", _music(last.vocal)) or re.search(r"[A-Ga-g]", _music(score.bars[end].vocal)):
                    break
                if not _music(last.instrumental).endswith("-"):
                    candidates.append((index, end))
        if not candidates:
            minimum = math.ceil(score.duration_s)
            raise ScoreError(f"The vocal passages and ending need about {minimum}s at {score.bpm} BPM. "
                             "Choose a longer duration, shorten verses/repeated choruses, or supply a shorter score. "
                             "No lyrics have been removed.")
        # Remove a complete instrumental phrase, including any internal ties.
        start, end = max(candidates, key=lambda span: span[1] - span[0])
        del score.bars[start:end]
        removed += end - start
    fitted = score.text() if removed else text
    checked = inspect(fitted)
    return fitted, {"original_duration_s": round(original_s, 2), "planned_duration_s": round(checked.duration_s, 2),
                    "bpm": score.bpm, "removed_instrumental_bars": removed,
                    "vocal_bars_preserved": True, "tempo_preserved": True}
