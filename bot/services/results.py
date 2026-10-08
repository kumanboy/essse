"""Validate and normalize essay-checking results.

The model is trusted only for:
- the 12 individual criterion scores;
- the five recommendations;
- the final teacher conclusion.

Python is authoritative for:
- /24 total;
- /75 conversion;
- final output formatting.

Small formatting differences from the model must not turn a valid
evaluation into a technical failure.
"""

import re
from decimal import Decimal


INTRO = (
    "Assalomu alaykum.\n"
    "Sizning essengiz Sardor Toshmuhammadov tomonidan "
    "UZBMB baholash mezonlari asosida tekshirildi."
)

CRITERIA = (
    "Publitsistik uslub",
    "Qarashlar va shaxsiy fikr",
    "Dalillash",
    "Kirish–asosiy qism–xulosa",
    "Matn qurilishi va xatboshilar",
    "Izchillik va takror",
    "Imlo",
    "Punktuatsiya",
    "Qo‘shimcha qo‘llash",
    "So‘z qo‘llash uslubiyati",
    "Leksik boylik",
    "Nutq sofligi",
)

# Fixed UZBMB conversion matrix.
# Index = score * 2.
SCALE = (
    0,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    49,
    50,
    51,
    52,
    53,
    54,
    55,
    56,
    57,
    58,
    59,
    60,
    61,
    62,
    63,
    64,
    65,
    66,
    67,
    68,
    69,
    70,
    71,
    72,
    73,
    74,
    75,
)

STOP_SCORES = {
    "mavzuga mos emas": Decimal("2"),
    "100 so‘zdan kam": Decimal("2"),
    "ko‘chirilgan": Decimal("2"),
    "esse yo‘q": Decimal("0"),
    "faqat kirish": Decimal("0"),
    "to‘liq kirill": Decimal("0"),
}

RECOMMENDATIONS = "BALLNI OSHIRISH UCHUN TAVSIYALAR (5 ta):"
CONCLUSION = "UMUMIY XULOSA:"

ALLOWED_SCORES = {
    Decimal("0"),
    Decimal("0.5"),
    Decimal("1"),
    Decimal("1.5"),
    Decimal("2"),
}


def scale_score(score) -> int:
    """Convert /24 score to /75 using only the official fixed matrix."""
    score = Decimal(str(score))
    units = score * 2

    if units != units.to_integral_value():
        raise ValueError(f"invalid_half_point_total:{score}")

    if units < 0 or units > 48:
        raise ValueError(f"total_out_of_range:{score}")

    return SCALE[int(units)]


def totals(score) -> str:
    """Generate totals ourselves instead of trusting model arithmetic."""
    score = Decimal(str(score))

    return (
        f"Jami ball: {score:g} / 24\n\n"
        f"75 ballik shkala bo‘yicha: {scale_score(score)} / 75"
    )


def _clean_model_text(text: str) -> str:
    """Remove harmless formatting differences produced by models."""
    if not isinstance(text, str):
        raise ValueError("result_not_string")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = text.strip()

    # Remove surrounding Markdown code fence if a model added one.
    if text.startswith("```"):
        text = re.sub(r"^```(?:text|plaintext)?\s*", "", text, count=1)
        text = re.sub(r"\s*```$", "", text, count=1)

    # Telegram output is plain text anyway.
    # Remove accidental Markdown emphasis.
    text = text.replace("**", "").replace("__", "")

    # Remove Markdown heading prefixes such as ### BAHOLASH NATIJALARI:
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)

    # Avoid excessive model-generated blank space.
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text.strip()


def _normalize_label(value: str) -> str:
    """Normalize harmless Unicode differences in criterion names."""
    value = value.strip()

    # Uzbek apostrophe variants.
    value = value.translate(
        str.maketrans(
            {
                "ʻ": "‘",
                "ʼ": "‘",
                "’": "‘",
                "`": "‘",
                "´": "‘",
            }
        )
    )

    # Dash variants.
    value = re.sub(r"[‐-‒–—−]", "-", value)

    # Ignore spacing around internal dashes.
    value = re.sub(r"\s*-\s*", "-", value)

    value = re.sub(r"\s+", " ", value)

    return value.casefold().strip()


CRITERION_LOOKUP = {
    _normalize_label(name): name
    for name in CRITERIA
}

# Safe aliases in case a model uses the rubric heading instead
# of the required final-output label.
CRITERION_ALIASES = {
    _normalize_label("Qarashlar va shaxsiy fikr yoritilishi"):
        "Qarashlar va shaxsiy fikr",

    _normalize_label("So‘z qo‘llash bilan bog‘liq uslubiy xatolik"):
        "So‘z qo‘llash uslubiyati",

    _normalize_label("Leksik xilma-xillik"):
        "Leksik boylik",
}


def _criterion_name(value: str) -> str | None:
    key = _normalize_label(value)

    if key in CRITERION_LOOKUP:
        return CRITERION_LOOKUP[key]

    return CRITERION_ALIASES.get(key)


def _validate_intro(text: str) -> None:
    """Require the expected teacher identity without being punctuation-fragile."""
    if not re.match(r"^Assalomu alaykum[.!]?", text):
        raise ValueError("invalid_result_intro")

    intro_area = text[:500]

    if (
        "Sizning essengiz Sardor Toshmuhammadov tomonidan"
        not in intro_area
    ):
        raise ValueError("missing_teacher_intro")


def _parse_stop(text: str) -> str | None:
    """Return normalized STOP result, or None if this is not a STOP answer."""
    if "STOP NATIJA:" not in text:
        return None

    if "BAHOLASH NATIJALARI:" in text:
        raise ValueError("conflicting_stop_and_normal_result")

    match = re.search(
        r"STOP NATIJA:\s*"
        r"(?:\n\s*)*"
        r"Sabab:\s*([^\n]+)",
        text,
        re.IGNORECASE,
    )

    if not match:
        raise ValueError("stop_reason_missing")

    reason = match.group(1).strip()

    # Remove punctuation accidentally added after the reason.
    reason = reason.rstrip(". ")

    if reason not in STOP_SCORES:
        raise ValueError(f"invalid_stop_reason:{reason[:80]}")

    score = STOP_SCORES[reason]

    return (
        INTRO
        + "\n\nSTOP NATIJA:\n\n"
        + f"Sabab: {reason}"
        + "\n\n"
        + totals(score)
    )


def _parse_scores(score_block: str) -> dict[str, Decimal]:
    """Parse the 12 criterion scores without trusting model totals."""
    parsed: dict[str, Decimal] = {}

    # Criterion lines end with one allowed score.
    #
    # Accepted examples:
    #
    # Publitsistik uslub — 2
    # Publitsistik uslub - 2
    # Publitsistik uslub: 2
    # Publitsistik uslub — 2.0
    #
    score_line = re.compile(
        r"^\s*"
        r"(?P<name>.+?)"
        r"\s+(?:—|–|-|:)\s*"
        r"(?P<score>0(?:\.0|\.5)?|1(?:\.0|\.5)?|2(?:\.0)?)"
        r"\s*$"
    )

    for raw_line in score_block.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        # Ignore model-generated totals completely.
        lower = line.casefold()

        if lower.startswith("jami ball"):
            continue

        if lower.startswith("75 ballik shkala"):
            continue

        # Ignore accidental list bullet before a criterion.
        line = re.sub(r"^[•*]\s*", "", line)

        match = score_line.match(line)

        if not match:
            # If it looks like a criterion/score line but is malformed,
            # make the DB diagnostic useful.
            if any(
                _normalize_label(name) in _normalize_label(line)
                for name in CRITERIA
            ):
                raise ValueError(
                    "malformed_score_line:"
                    + line[:100]
                )

            # Harmless extra text in the score block should not cause a
            # technical failure unless it replaces a required criterion.
            continue

        raw_name = match.group("name").strip()
        canonical_name = _criterion_name(raw_name)

        if canonical_name is None:
            # It may be a total-like or unrelated line.
            continue

        if canonical_name in parsed:
            raise ValueError(
                f"duplicate_criterion:{canonical_name}"
            )

        score = Decimal(match.group("score"))

        if score not in ALLOWED_SCORES:
            raise ValueError(
                f"invalid_criterion_score:"
                f"{canonical_name}:{score}"
            )

        parsed[canonical_name] = score

    missing = [
        name
        for name in CRITERIA
        if name not in parsed
    ]

    if missing:
        raise ValueError(
            "missing_criteria:"
            + ",".join(missing)
        )

    if len(parsed) != 12:
        raise ValueError(
            f"wrong_criterion_count:{len(parsed)}"
        )

    return parsed


def _validate_recommendations(
    recommendations: str,
    conclusion: str,
) -> None:
    """Validate useful structural requirements while tolerating 1. vs 1)."""
    item_numbers = re.findall(
        r"(?m)^\s*([1-5])[\.\)]\s+",
        recommendations,
    )

    if item_numbers != ["1", "2", "3", "4", "5"]:
        raise ValueError(
            "invalid_recommendation_numbers:"
            + ",".join(item_numbers)
        )

    parts = re.split(
        r"(?m)^\s*[1-5][\.\)]\s+",
        recommendations,
    )[1:]

    if len(parts) != 5:
        raise ValueError(
            f"wrong_recommendation_count:{len(parts)}"
        )

    if any(not part.strip() for part in parts):
        raise ValueError("empty_recommendation")

    if "Qisqasi, maslahatim" not in conclusion:
        raise ValueError(
            "required_teacher_closing_missing"
        )

    forbidden_sections = (
        "BAHOLASH NATIJALARI:",
        "STOP NATIJA:",
        "Kirish qismi:",
        "Asosiy qism:",
        "Xulosa:",
        "Imlo:",
        "Punktuatsiya:",
        "MATN BO‘YICHA IZOHLAR",
    )

    feedback = recommendations + "\n" + conclusion

    for section in forbidden_sections:
        if section in feedback:
            raise ValueError(
                f"unexpected_extra_section:{section}"
            )


def validate_result(text: str, essay: str) -> str:
    """Validate, normalize and rebuild one essay result."""
    text = _clean_model_text(text)

    _validate_intro(text)

    if "MATN BO‘YICHA IZOHLAR" in text:
        raise ValueError(
            "forbidden_matn_boyicha_izohlar"
        )

    # ---------------------------------------------------------
    # STOP CASE
    # ---------------------------------------------------------

    stop_result = _parse_stop(text)

    if stop_result is not None:
        return stop_result

    # ---------------------------------------------------------
    # LOCAL WORD-COUNT SAFETY
    # ---------------------------------------------------------

    word_count = len(essay.split())

    if word_count < 100:
        raise ValueError(
            f"short_essay_without_stop:{word_count}"
        )

    # ---------------------------------------------------------
    # FIND NORMAL RESULT SECTIONS
    # ---------------------------------------------------------

    score_heading = "BAHOLASH NATIJALARI:"

    score_pos = text.find(score_heading)
    rec_pos = text.find(RECOMMENDATIONS)
    conclusion_pos = text.find(CONCLUSION)

    if score_pos == -1:
        raise ValueError(
            "baholash_heading_missing"
        )

    if rec_pos == -1:
        raise ValueError(
            "recommendations_heading_missing"
        )

    if conclusion_pos == -1:
        raise ValueError(
            "conclusion_heading_missing"
        )

    if not (
        score_pos
        < rec_pos
        < conclusion_pos
    ):
        raise ValueError(
            "result_sections_wrong_order"
        )

    score_block = text[
        score_pos + len(score_heading):
        rec_pos
    ].strip()

    recommendations = text[
        rec_pos + len(RECOMMENDATIONS):
        conclusion_pos
    ].strip()

    conclusion = text[
        conclusion_pos + len(CONCLUSION):
    ].strip()

    if not score_block:
        raise ValueError(
            "empty_score_block"
        )

    if not recommendations:
        raise ValueError(
            "empty_recommendations"
        )

    if not conclusion:
        raise ValueError(
            "empty_conclusion"
        )

    # ---------------------------------------------------------
    # PARSE THE 12 AUTHORITATIVE CRITERION SCORES
    # ---------------------------------------------------------

    parsed_scores = _parse_scores(score_block)

    scores = [
        parsed_scores[name]
        for name in CRITERIA
    ]

    # Python, not the model, calculates totals.
    total = sum(
        scores,
        Decimal("0"),
    )

    if total < 0 or total > 24:
        raise ValueError(
            f"calculated_total_out_of_range:{total}"
        )

    # ---------------------------------------------------------
    # FEEDBACK VALIDATION
    # ---------------------------------------------------------

    _validate_recommendations(
        recommendations,
        conclusion,
    )

    # ---------------------------------------------------------
    # REBUILD CLEAN AUTHORITATIVE OUTPUT
    # ---------------------------------------------------------

    criteria_output = "\n\n".join(
        f"{name} — {score:g}"
        for name, score in zip(
            CRITERIA,
            scores,
        )
    )

    return (
        INTRO
        + "\n\n"
        + score_heading
        + "\n\n"
        + criteria_output
        + "\n\n"
        + totals(total)
        + "\n\n"
        + RECOMMENDATIONS
        + "\n\n"
        + recommendations
        + "\n\n"
        + CONCLUSION
        + "\n\n"
        + conclusion
    )


def split_result(
    text: str,
    limit: int = 3900,
) -> list[str]:
    """Split a long result safely for Telegram."""

    def size(value: str) -> int:
        # Telegram's length behavior is safest when measured
        # conservatively in UTF-16 code units.
        return (
            len(value.encode("utf-16-le"))
            // 2
        )

    parts: list[str] = []
    current = ""

    for paragraph in text.split("\n\n"):
        addition = (
            ("\n\n" if current else "")
            + paragraph
        )

        if size(current + addition) <= limit:
            current += addition
            continue

        if current:
            parts.append(current)
            current = ""

        while size(paragraph) > limit:
            end = 0
            units = 0

            for char in paragraph:
                char_units = size(char)

                if (
                    units + char_units
                    > limit
                ):
                    break

                units += char_units
                end += 1

            if end <= 0:
                raise ValueError(
                    "unable_to_split_result"
                )

            boundary = paragraph.rfind(
                " ",
                0,
                end,
            )

            if boundary > end // 2:
                end = boundary

            part = paragraph[:end].rstrip()

            if part:
                parts.append(part)

            paragraph = (
                paragraph[end:]
                .lstrip()
            )

        current = paragraph

    if current:
        parts.append(current)

    return parts
