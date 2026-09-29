"""Numbers for narration: read them however they're written (digits or words) and write them the way they're spoken.

values(text)  -> every number in the text as a value: "$200,000", "88 million", "two hundred thousand",
                 "nineteen seventy-one" (a year), "eight-year-old"...
spoken(text)  -> digits rewritten as spoken words: "$200,000" -> "two hundred thousand dollars",
                 "1971" -> "nineteen seventy-one", "1970s" -> "nineteen seventies", "45%" -> "forty-five percent".
"""
import re

UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
SCALES = [(1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")]
WORD_VAL = {w: i for i, w in enumerate(UNITS)} | {w: i * 10 for i, w in enumerate(TENS) if w}
SCALE_VAL = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
ORDINAL = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
           "twelve": "twelfth"}
CURRENCY = {"$": "dollars", "€": "euros", "£": "pounds"}


def words(n: int) -> str:
    """0 .. 999,999,999,999 in words: 200000 -> 'two hundred thousand', 88 -> 'eighty-eight'."""
    if n < 20:
        return UNITS[n]
    if n < 100:
        return TENS[n // 10] + ("-" + UNITS[n % 10] if n % 10 else "")
    if n < 1000:
        return UNITS[n // 100] + " hundred" + (" " + words(n % 100) if n % 100 else "")
    for size, name in SCALES:
        if n >= size:
            return words(n // size) + " " + name + (" " + words(n % size) if n % size else "")
    return str(n)


def year(y: int) -> str:
    """1971 -> 'nineteen seventy-one', 2013 -> 'twenty thirteen', 2005 -> 'two thousand five', 1905 -> 'nineteen oh-five'."""
    hi, lo = divmod(y, 100)
    if 2000 <= y <= 2009:
        return "two thousand" + (" " + words(lo) if lo else "")
    if lo == 0:
        return words(hi) + " hundred"
    if lo < 10:
        return f"{words(hi)} oh-{words(lo)}"
    return f"{words(hi)} {words(lo)}"


def ordinal(n: int) -> str:
    w = words(n)
    last = re.split(r"[- ]", w)[-1]
    if last in ORDINAL:
        return w[: len(w) - len(last)] + ORDINAL[last]
    return w[:-1] + "ieth" if w.endswith("y") else w + "th"


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _say_number(s: str) -> str:
    v = _num(s)
    if "." in s.replace(",", ""):
        whole, frac = s.replace(",", "").split(".")
        return words(int(whole)) + " point " + " ".join(UNITS[int(d)] for d in frac)
    return words(int(v))


def spoken(text: str) -> str:
    """Rewrite digits so the voice (and the captions) say them the way a person would."""
    def money(m):
        amount, scale = m.group(2), m.group(3)
        return f"{_say_number(amount)}{' ' + scale.lower() if scale else ''} {CURRENCY[m.group(1)]}"
    text = re.sub(r"([$€£])\s?(\d[\d,]*(?:\.\d+)?)(?:\s?(million|billion|thousand))?\b", money, text, flags=re.I)
    text = re.sub(r"\b(\d[\d,]*(?:\.\d+)?)\s?%", lambda m: _say_number(m.group(1)) + " percent", text)
    text = re.sub(r"\b(1[0-9]|20)(\d)0s\b",
                  lambda m: (year(int(m.group(1) + m.group(2) + "0"))[:-1] + "ies") if m.group(2) != "0"
                  else year(int(m.group(1) + "00")) + "s", text)
    text = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: ordinal(int(m.group(1))), text)
    text = re.sub(r"(?<![\d,.$€£])\b(1[0-9]\d\d|20\d\d)\b(?![\d,]|\s?(?:million|billion|thousand|people|men|women))",
                  lambda m: year(int(m.group(1))), text)
    text = re.sub(r"\b\d[\d,]*(?:\.\d+)?\b", lambda m: _say_number(m.group(0)), text)
    return text


def _word_values(tokens: list[str]) -> list[float]:
    """Values of one run of number words ('two hundred thousand', 'nineteen seventy-one', 'eighty-eight million')."""
    parts = [t for t in tokens if t != "and"]
    if not parts:
        return []
    if any(t in SCALE_VAL for t in parts):
        total = current = 0
        for t in parts:
            if t in WORD_VAL:
                current += WORD_VAL[t]
            elif t == "hundred":
                current = (current or 1) * 100
            else:
                total += (current or 1) * SCALE_VAL[t]
                current = 0
        return [total + current]
    groups: list[int] = []
    for t in parts:
        v = WORD_VAL[t]
        if groups and groups[-1] >= 20 and groups[-1] % 10 == 0 and v < 10:
            groups[-1] += v
        else:
            groups.append(v)
    if len(groups) == 2 and 10 <= groups[0] <= 99 and groups[1] <= 99:  # "nineteen seventy-one"
        return [groups[0] * 100 + groups[1]]
    if len(groups) == 3 and groups[1] == 0:  # "nineteen oh five" (oh read as zero)
        return [groups[0] * 100 + groups[2]]
    return [float(g) for g in groups]


def values(text: str) -> set[float]:
    """Every number in the text, whether written in digits or words."""
    out: set[float] = set()
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)(?:\s?(million|billion|thousand))?", text, flags=re.I):
        try:
            v = _num(m.group(1))
        except ValueError:
            continue
        out.add(v * SCALE_VAL[m.group(2).lower()] if m.group(2) else v)
        out.add(v)
    for part in re.split(r"[.,;:!?()\"\n]", text.lower().replace("oh-", "zero ")):  # a run never crosses punctuation
        run: list[str] = []
        for t in re.findall(r"[a-z]+", part) + ["."]:
            if t in WORD_VAL or (t in SCALE_VAL and run) or (t == "and" and run):
                run.append(t)
            else:
                if any(x in WORD_VAL for x in run):
                    out.update(_word_values(run))
                run = []
    return out
