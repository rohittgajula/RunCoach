"""Reading a lab report he uploads — a PDF or a photo — into a draft panel.

The earlier version of `labs.py` said this was deliberately not built, because a
mis-read decimal point on a ferritin result is a number somebody might act on.
That reasoning still holds. What changed is who checks the number: nothing here
is saved. The extraction produces a *draft* that he confirms value by value
against the report still in his hand, and `as_printed` carries the exact text
each number was read from so the check is a glance, not a re-reading.

Four things keep the model away from anything it is bad at:

**Python converts the units, the model only reports them.** This is the real
hazard with Indian lab reports, and it is not OCR — it is that vitamin D comes
in ng/mL from one lab and nmol/L from the next, a factor of 2.5, with no change
in how the number looks. The model is asked for the unit exactly as printed; the
conversion is the table below. A unit nobody here recognises is a rejection, not
a guess.

**Python rejects the impossible.** `PLAUSIBLE` is what a real human result can
be, which is far wider than a reference range — it exists to catch the shifted
decimal point, not to second-guess a lab. Ferritin of 1,240 is a real (alarming)
result; ferritin of 124,000 is a misplaced comma.

**Nothing is dropped silently.** A row that fails any check comes back in
`rejected` with the reason, and a marker the app does not track comes back in
`not_tracked`. The alternative — a draft that is quietly four rows short — is
worse than a visible failure, because a missing ferritin looks exactly like a
ferritin that was never tested.

**The file is never stored.** It is read into memory, sent to the model, and
dropped when the request ends. A lab report carries his name, age and often his
address, so the only copy that persists is the one he already has.
"""

from __future__ import annotations

import base64
import datetime as dt
import io
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from analysis import bloodwork
from apps.athletes.models import Athlete
from apps.coaching.client import AIUnavailable, complete, model_for
from apps.coaching.services import check_budget, log_call

logger = logging.getLogger(__name__)

OPERATION = "lab_extract"
PROMPT_VERSION = "lab-extract-v1"

MAX_BYTES = 12 * 1024 * 1024
#: Pages read from a PDF. A full-body panel runs to three or four; past that it is
#: a different document and the athlete can crop it.
MAX_PAGES = 6
#: Below this much extracted text a PDF is a scan, not a digital report, and gets
#: rasterised and read as an image instead.
MIN_PDF_TEXT_CHARS = 200
RASTER_SCALE = 2.0  # ~150 dpi: enough for small print, small enough to send.

KEYS: tuple[str, ...] = tuple(m.key for m in bloodwork.MARKERS)
MarkerKey = Literal[KEYS + ("other",)]  # type: ignore[valid-type]

#: Unit the app stores each marker in. Always the lab's conventional unit here.
CANONICAL: dict[str, str] = {m.key: m.unit for m in bloodwork.MARKERS}

#: Normalised printed unit -> (canonical unit, multiplier). Keys are lowercased
#: with spaces and micro-signs flattened by `_unit_key`. A factor of 1.0 is an
#: alias, not a conversion.
#:
#: SI-to-conventional factors, each the standard one:
#:   vitamin D   nmol/L  -> ng/mL   / 2.496
#:   B12         pmol/L  -> pg/mL   x 1.355
#:   folate      nmol/L  -> ng/mL   / 2.266
#:   creatinine  umol/L  -> mg/dL   / 88.4
#:   calcium     mmol/L  -> mg/dL   x 4.008
#:   magnesium   mmol/L  -> mg/dL   x 2.43
#:   lipids      mmol/L  -> mg/dL   x 38.67
UNITS: dict[str, dict[str, tuple[str, float]]] = {
    "ferritin": {"ng/ml": ("ng/mL", 1.0), "ug/l": ("ng/mL", 1.0), "mcg/l": ("ng/mL", 1.0),
                 "pmol/l": ("ng/mL", 1 / 2.247)},
    "hemoglobin": {"g/dl": ("g/dL", 1.0), "gm/dl": ("g/dL", 1.0), "g%": ("g/dL", 1.0),
                   "g/l": ("g/dL", 0.1), "mmol/l": ("g/dL", 1.611)},
    "vitamin_d": {"ng/ml": ("ng/mL", 1.0), "ug/l": ("ng/mL", 1.0),
                  "nmol/l": ("ng/mL", 1 / 2.496)},
    "vitamin_b12": {"pg/ml": ("pg/mL", 1.0), "ng/l": ("pg/mL", 1.0),
                    "pmol/l": ("pg/mL", 1.355)},
    "tsh": {"miu/l": ("mIU/L", 1.0), "uiu/ml": ("mIU/L", 1.0), "miu/ml": ("mIU/L", 1000.0),
            "iu/ml": ("mIU/L", 1_000_000.0), "uu/ml": ("mIU/L", 1.0)},
    "vitamin_b9": {"ng/ml": ("ng/mL", 1.0), "ug/l": ("ng/mL", 1.0),
                   "nmol/l": ("ng/mL", 1 / 2.266)},
    "hba1c": {"%": ("%", 1.0), "percent": ("%", 1.0)},
    "creatinine": {"mg/dl": ("mg/dL", 1.0), "umol/l": ("mg/dL", 1 / 88.4)},
    "alt": {"u/l": ("U/L", 1.0), "iu/l": ("U/L", 1.0), "ukat/l": ("U/L", 60.0)},
    "cholesterol_total": {"mg/dl": ("mg/dL", 1.0), "mmol/l": ("mg/dL", 38.67)},
    "hdl": {"mg/dl": ("mg/dL", 1.0), "mmol/l": ("mg/dL", 38.67)},
    "ldl": {"mg/dl": ("mg/dL", 1.0), "mmol/l": ("mg/dL", 38.67)},
    "vitamin_b6": {"ng/ml": ("ng/mL", 1.0), "ug/l": ("ng/mL", 1.0),
                   "nmol/l": ("ng/mL", 1 / 5.91)},
    "calcium": {"mg/dl": ("mg/dL", 1.0), "mmol/l": ("mg/dL", 4.008),
                "meq/l": ("mg/dL", 2.004)},
    "magnesium": {"mg/dl": ("mg/dL", 1.0), "mmol/l": ("mg/dL", 2.43),
                  "meq/l": ("mg/dL", 1.215)},
}

#: What a real human result can be, in the canonical unit. Wide on purpose: this
#: catches a shifted decimal point, not an unusual patient. HbA1c tops out at 20
#: because higher is not survivable; ferritin runs to 10,000 because
#: haemochromatosis and liver disease genuinely reach it.
PLAUSIBLE: dict[str, tuple[float, float]] = {
    "ferritin": (0.1, 10_000.0),
    "hemoglobin": (2.0, 25.0),
    "vitamin_d": (1.0, 400.0),
    "vitamin_b12": (20.0, 20_000.0),
    "tsh": (0.001, 500.0),
    "vitamin_b9": (0.2, 100.0),
    "hba1c": (2.0, 20.0),
    "creatinine": (0.1, 25.0),
    "alt": (1.0, 5_000.0),
    "cholesterol_total": (40.0, 800.0),
    "hdl": (5.0, 200.0),
    "ldl": (10.0, 600.0),
    "vitamin_b6": (0.5, 500.0),
    "calcium": (4.0, 20.0),
    "magnesium": (0.3, 10.0),
}

SYSTEM = """You transcribe a pathology report into structured rows. You are a \
transcriber, not an interpreter.

For every result on the report, give one row with:
- `printed_name`: the test name exactly as the report prints it.
- `key`: which of the listed markers it is, or "other" if it is not one of them.
- `as_printed`: the result value exactly as it appears, character for character, \
including any < or > sign. Do not round, reformat or convert it.
- `value`: that same number as a decimal. If the report prints "<5", use 5.
- `unit`: the unit exactly as the report prints it. Never convert a unit and never \
substitute the unit you think is conventional — if it says nmol/L, write nmol/L.
- `ref_low` / `ref_high`: the reference range this report prints for this test, as \
numbers. Null if it prints none. For a one-sided range like "<200", set only ref_high.

Also give `taken_on` (the date the sample was collected, YYYY-MM-DD, null if not \
printed — prefer collection date over report/print date) and `lab` (the laboratory's name).

Rules:
- Transcribe only what is printed. Never infer, complete or correct a value.
- If a value is unreadable or ambiguous, leave it out rather than guessing, and say \
so in `unreadable`.
- Do not calculate anything, including ratios the report itself did not print.
- Do not comment on the results or give any advice."""


class ExtractedReading(BaseModel):
    model_config = {"extra": "forbid"}

    printed_name: str = Field(description="Test name as the report prints it.")
    key: MarkerKey
    as_printed: str = Field(description="The value exactly as printed.")
    value: float
    unit: str = Field(description="Unit exactly as printed.")
    ref_low: float | None = None
    ref_high: float | None = None


class ExtractedPanel(BaseModel):
    model_config = {"extra": "forbid"}

    taken_on: str | None = Field(default=None, description="YYYY-MM-DD or null.")
    lab: str = ""
    readings: list[ExtractedReading]
    unreadable: list[str] = Field(
        default_factory=list, description="Test names present but not legible."
    )


def _unit_key(unit: str) -> str:
    """Normalise a printed unit: case, spaces, micro-signs and 'per' spellings."""
    s = (unit or "").strip().lower()
    for micro in ("µ", "μ"):  # MICRO SIGN, GREEK SMALL LETTER MU
        s = s.replace(micro, "u")
    s = s.replace("litre", "l").replace("liter", "l")
    s = re.sub(r"\s+", "", s)
    s = s.replace("per", "/")
    return s


def _convert(key: str, value: float, unit: str) -> tuple[float, str, str | None, float]:
    """(value in the canonical unit, canonical unit, a note when the row needs one,
    the factor used).

    The factor is returned because the reference range the report printed is in the
    same unit as the value, and has to move with it. Getting that wrong is quieter
    than getting the value wrong and just as bad: a vitamin D of 17 ng/mL against a
    range of "75–250" — the nmol/L numbers left alone — is a row that looks precise
    and compares two different scales.

    The note is what the review screen shows under the number — either that a
    conversion happened, or that the report printed no unit at all. Both are
    things he should see before saving; neither is an error.

    Raises ValueError when the printed unit is not one this table knows. A wrong
    unit is a wrong number, so an unknown one is handed back rather than assumed.
    """
    canonical = CANONICAL[key]
    table = UNITS.get(key, {})
    printed = _unit_key(unit)
    if not printed:
        return value, canonical, f"the report printed no unit — read as {canonical}", 1.0
    if printed not in table:
        raise ValueError(
            f"unit “{unit.strip()}” is not one I know for {bloodwork.BY_KEY[key].label}"
        )
    target, factor = table[printed]
    if factor == 1.0:
        return value, target, None, 1.0
    return value * factor, target, f"converted from {value:g} {unit.strip()}", factor


def _tidy(value: float, factor: float) -> float:
    """A converted number, rounded to the precision its source actually had.

    A unit conversion cannot create precision. The report said 42.5 nmol/L — three
    figures — so 17.027 ng/mL is three figures of vitamin D and two of arithmetic,
    and a number carrying decimals the lab never measured invites him to trust it
    more than the report behind it. Unconverted values are returned untouched,
    because those ARE what the report printed.
    """
    if factor == 1.0 or value == 0:
        return value
    from math import floor, log10

    digits = 3 - 1 - floor(log10(abs(value)))
    return round(value, max(0, min(digits, 6)))


def _clean_date(raw: str | None, today: dt.date) -> tuple[dt.date | None, str | None]:
    if not raw:
        return None, "the report did not print a collection date"
    try:
        day = dt.date.fromisoformat(raw.strip()[:10])
    except (ValueError, AttributeError):
        return None, f"could not read the date “{raw}”"
    if day > today:
        return None, f"the date read as {day}, which is in the future"
    if day < today - dt.timedelta(days=365 * 20):
        return None, f"the date read as {day}, which is over 20 years ago"
    return day, None


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = [(page.extract_text() or "") for page in reader.pages[:MAX_PAGES]]
    return "\n".join(parts).strip()


def _pdf_image(data: bytes) -> str:
    """First page as a PNG data URL, for a PDF that is a scan.

    One page: a scanned multi-page report is beyond what a single vision call
    should be trusted with, and the caller says so in `source_note`.
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(io.BytesIO(data))
    try:
        bitmap = doc[0].render(scale=RASTER_SCALE)
        buffer = io.BytesIO()
        bitmap.to_pil().save(buffer, format="PNG")
    finally:
        doc.close()
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"


def _prepare(data: bytes, content_type: str | None, filename: str) -> tuple[str, str | None, str]:
    """(prompt text, image data URL or None, note for the athlete)."""
    kind = (content_type or "").lower()
    is_pdf = kind == "application/pdf" or filename.lower().endswith(".pdf")

    if is_pdf:
        try:
            text = _pdf_text(data)
        except Exception as exc:  # noqa: BLE001 — a broken PDF is the athlete's answer
            raise ValueError("I could not open that PDF. A photo of the report works too.") from exc
        if len(text) >= MIN_PDF_TEXT_CHARS:
            pages = text[:40_000]
            return (
                f'The report, as text extracted from the PDF:\n"""\n{pages}\n"""',
                None,
                "Read from the PDF's own text.",
            )
        try:
            image = _pdf_image(data)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                "That PDF is a scan and I could not turn it into an image. "
                "A photo of the report works too."
            ) from exc
        return (
            "The report is attached as an image of the first page of a scanned PDF.",
            image,
            "That PDF is a scan, so only its first page was read. Check nothing is missing.",
        )

    if not kind.startswith("image/"):
        raise ValueError("Upload a PDF or a photo of the report.")
    return (
        "The report is attached as a photo.",
        f"data:{kind};base64,{base64.b64encode(data).decode()}",
        "Read from the photo.",
    )


def extract_panel(athlete: Athlete, *, data: bytes, content_type: str | None,
                  filename: str = "", today: dt.date | None = None) -> dict:
    """A draft panel from an uploaded report. Never saved.

    Raises ValueError for anything the athlete can fix (wrong file type, an
    unopenable PDF) and AIUnavailable for anything they cannot.
    """
    if not data:
        raise ValueError("That file was empty.")
    if len(data) > MAX_BYTES:
        raise ValueError(f"The file must be under {MAX_BYTES // (1024 * 1024)} MB.")
    today = today or athlete.local_today

    prompt, image, source_note = _prepare(data, content_type, filename)
    known = ", ".join(f"{m.key} ({m.label})" for m in bloodwork.MARKERS)
    prompt = f"{prompt}\n\nThe markers this app tracks:\n{known}\n\nToday is {today}."

    model = model_for(OPERATION)
    check_budget(athlete, OPERATION, model)
    try:
        result, stats = complete(
            operation=OPERATION, system=SYSTEM, user=prompt,
            schema=ExtractedPanel, image_data_url=image,
        )
    except AIUnavailable as exc:
        log_call(athlete, OPERATION, {"model": model}, exc, PROMPT_VERSION)
        raise
    log_call(athlete, OPERATION, stats, None, PROMPT_VERSION)

    return _validate(result, today=today, source_note=source_note)


def _validate(result: ExtractedPanel, *, today: dt.date, source_note: str) -> dict:
    readings: list[dict] = []
    rejected: list[dict] = []
    not_tracked: list[str] = []
    seen: set[str] = set()

    for row in result.readings:
        printed = (row.printed_name or "").strip()[:120]
        if row.key == "other" or row.key not in CANONICAL:
            if printed:
                not_tracked.append(printed)
            continue
        label = bloodwork.BY_KEY[row.key].label
        if row.key in seen:
            rejected.append({"printed_name": printed or label,
                             "reason": f"{label} appeared twice; only the first was kept"})
            continue

        try:
            value, unit, unit_note, factor = _convert(row.key, float(row.value), row.unit)
        except (ValueError, TypeError, OverflowError) as exc:
            rejected.append({"printed_name": printed or label, "reason": str(exc)})
            continue

        low, high = PLAUSIBLE[row.key]
        if not (low <= value <= high):
            rejected.append({
                "printed_name": printed or label,
                "reason": (f"{value:g} {unit} is outside anything a real {label} result can be "
                           f"({low:g}–{high:g}) — most likely a misread decimal point"),
            })
            continue

        ref_low, ref_high = _ref_range(row, row.key, factor)
        seen.add(row.key)
        readings.append({
            "key": row.key, "label": label, "unit": unit,
            "value": _tidy(value, factor),
            "as_printed": (row.as_printed or "").strip()[:40],
            "printed_name": printed or label,
            "printed_unit": (row.unit or "").strip()[:24],
            "unit_note": unit_note,
            "ref_low": ref_low, "ref_high": ref_high,
            "runner_key": bloodwork.BY_KEY[row.key].runner_key,
        })

    taken_on, date_note = _clean_date(result.taken_on, today)
    # Runner markers first: the same order as the typed form, so the review screen
    # puts the five that matter where his eye already goes.
    readings.sort(key=lambda r: (not r["runner_key"], r["label"]))
    return {
        "taken_on": taken_on,
        "date_note": date_note,
        "lab": (result.lab or "").strip()[:120],
        "readings": readings,
        "rejected": rejected,
        "not_tracked": sorted(set(not_tracked)),
        "unreadable": [u.strip()[:120] for u in (result.unreadable or [])][:20],
        "missing_runner_markers": [
            bloodwork.BY_KEY[k].label for k in bloodwork.RUNNER_KEYS if k not in seen
        ],
        "source_note": source_note,
        "standing_note": (
            "Check every number against the report before you save it. This was read "
            "by a model and the file itself was not kept."
        ),
    }


def _ref_range(row: ExtractedReading, key: str,
               factor: float) -> tuple[float | None, float | None]:
    """The lab's own printed range, converted with the value and kept only when it
    makes sense.

    `factor` is the one applied to the value: the range is printed in the same unit,
    so it converts the same way. Without that, a converted row compares a canonical
    value against a foreign-unit range — and because the range is only ever read, not
    recomputed, nothing downstream would notice.

    A range wider than plausible, or inverted, is a misread of the report's layout —
    the commonest being picking up the neighbouring row's numbers. Dropping it falls
    back to the app's typical range, which `range_source` then says out loud.
    """
    low = row.ref_low * factor if row.ref_low is not None else None
    high = row.ref_high * factor if row.ref_high is not None else None
    floor, ceiling = PLAUSIBLE[key]
    if low is not None and not (floor <= low <= ceiling):
        low = None
    if high is not None and not (floor <= high <= ceiling):
        high = None
    if low is not None and high is not None and low >= high:
        return None, None
    return (_tidy(low, factor) if low is not None else None,
            _tidy(high, factor) if high is not None else None)
