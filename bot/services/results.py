"""Validate the rubric's plain-text format; never trust model arithmetic."""

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

# Literal transcription of the supplied matrix,
# indexed by half-point units.
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
    "mavzuga mos emas": 2,
    "100 so‘zdan kam": 2,
    "ko‘chirilgan": 2,
    "esse yo‘q": 0,
    "faqat kirish": 0,
    "to‘liq kirill": 0,
}

RECOMMENDATIONS = "BALLNI OSHIRISH UCHUN TAVSIYALAR (5 ta):"
CONCLUSION = "UMUMIY XULOSA:"


def scale_score(score) -> int:
    """
    Convert the authoritative /24 score to /75
    using the fixed lookup matrix only.
    """
    units = Decimal(str(score)) * 2

    if units != units.to_integral_value() or not 0 <= units <= 48:
        raise ValueError("Invalid total")

    return SCALE[int(units)]


def totals(score) -> str:
    """
    Build authoritative totals.

    IMPORTANT:
    These values are calculated by Python,
    not trusted from the model response.
    """
    return (
        f"Jami ball: {score:g} / 24\n\n"
        f"75 ballik shkala bo‘yicha: {scale_score(score)} / 75"
    )


def validate_result(text: str, essay: str) -> str:
    """
    Validate the model's output structure.

    The model decides the individual 12 criterion scores,
    recommendations, and conclusion.

    Python is authoritative for:
    - summing the 12 criterion scores;
    - calculating the /24 total;
    - converting to the /75 scale.

    Model-generated arithmetic is intentionally ignored.
    """

    text = text.strip()

    if not text.startswith(INTRO):
        raise ValueError("Invalid result intro")

    if "MATN BO‘YICHA IZOHLAR" in text:
        raise ValueError("Forbidden result section")

    body = text[len(INTRO):].strip()

    # We still require the model to follow the expected output format,
    # but the numerical totals it prints are NOT trusted.
    total_pattern = (
        r"Jami ball: ([0-9]+(?:\.5)?) / 24\s+"
        r"75 ballik shkala bo‘yicha: ([0-9]+) / 75"
    )

    # ---------------------------------------------------------
    # STOP RESULT
    # ---------------------------------------------------------

    if body.startswith("STOP NATIJA:"):
        match = re.fullmatch(
            r"STOP NATIJA:\s+"
            r"Sabab: ([^\n]+)\s+"
            + total_pattern,
            body,
        )

        if not match:
            raise ValueError("Invalid STOP result")

        reason = match[1].strip()

        if reason not in STOP_SCORES:
            raise ValueError("Invalid STOP reason")

        # Authoritative score comes from our own rules.
        score = STOP_SCORES[reason]

        # IMPORTANT:
        # Do NOT validate model arithmetic here.
        #
        # Even if the model writes the wrong /24 or /75 value,
        # reconstruct the correct values ourselves.
        return (
            INTRO
            + "\n\nSTOP NATIJA:\n\n"
            + "Sabab: "
            + reason
            + "\n\n"
            + totals(score)
        )

    # ---------------------------------------------------------
    # SHORT ESSAY SAFETY CHECK
    # ---------------------------------------------------------

    if len(essay.split()) < 100:
        raise ValueError("Short essay requires official STOP result")

    # ---------------------------------------------------------
    # NORMAL 12-CRITERIA RESULT
    # ---------------------------------------------------------

    pattern = r"BAHOLASH NATIJALARI:\s+"

    for name in CRITERIA:
        pattern += (
            re.escape(name)
            + r" — (0|0\.5|1|1\.5|2)\s+"
        )

    pattern += (
        total_pattern
        + r"\s+"
        + re.escape(RECOMMENDATIONS)
        + r"\s+(.+?)\s+"
        + re.escape(CONCLUSION)
        + r"\s+(.+)"
    )

    match = re.fullmatch(pattern, body, re.S)

    if not match:
        raise ValueError("Malformed rubric result")

    # Criterion scores are the only numerical grading values
    # we trust from the model.
    scores = [
        Decimal(match[i])
        for i in range(1, 13)
    ]

    # Python calculates the authoritative total.
    total = sum(scores)

    # IMPORTANT:
    # We intentionally ignore:
    #
    # match[13] -> model-generated /24 total
    # match[14] -> model-generated /75 total
    #
    # They may be wrong even when all 12 criterion scores
    # are valid. We recalculate both deterministically.

    recommendations = match[15].strip()
    conclusion = match[16].strip()

    # ---------------------------------------------------------
    # RECOMMENDATION VALIDATION
    # ---------------------------------------------------------

    items = re.findall(
        r"(?m)^(\d+)\.\s+",
        recommendations,
    )

    if items != ["1", "2", "3", "4", "5"]:
        raise ValueError("Exactly five recommendations required")

    if "Qisqasi, maslahatim" not in conclusion:
        raise ValueError("Required teacher closing missing")

    recommendation_parts = re.split(
        r"(?m)^\d+\.\s+",
        recommendations,
    )[1:]

    if any(
        not part.strip()
        for part in recommendation_parts
    ):
        raise ValueError("Empty recommendation")

    # ---------------------------------------------------------
    # FORBIDDEN EXTRA SECTIONS
    # ---------------------------------------------------------

    forbidden_sections = (
        "BAHOLASH NATIJALARI:",
        "STOP NATIJA:",
        "Kirish qismi:",
        "Asosiy qism:",
        "Imlo:",
        "Punktuatsiya:",
        "MATN BO‘YICHA IZOHLAR",
    )

    feedback_text = recommendations + conclusion

    if any(
        section in feedback_text
        for section in forbidden_sections
    ):
        raise ValueError("Unexpected extra section")

    # ---------------------------------------------------------
    # REBUILD FINAL AUTHORITATIVE RESULT
    # ---------------------------------------------------------

    criteria_output = "\n\n".join(
        f"{name} — {score:g}"
        for name, score in zip(CRITERIA, scores)
    )

    return (
        INTRO
        + "\n\nBAHOLASH NATIJALARI:\n\n"
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
    """
    Split long Telegram results safely.

    Prefer paragraph boundaries first,
    then word boundaries.

    Telegram limits are conservatively measured
    using UTF-16 code units.
    """

    def size(value: str) -> int:
        return len(
            value.encode("utf-16-le")
        ) // 2

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
                char_size = size(char)

                if units + char_size > limit:
                    break

                units += char_size
                end += 1

            # Prefer splitting at a nearby space.
            boundary = paragraph.rfind(
                " ",
                0,
                end,
            )

            if boundary > end // 2:
                end = boundary

            parts.append(
                paragraph[:end]
            )

            paragraph = (
                paragraph[end:]
                .lstrip()
            )

        current = paragraph

    if current:
        parts.append(current)

    return parts
