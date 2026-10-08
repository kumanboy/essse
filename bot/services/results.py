"""Validate the rubric's plain-text format; never trust model arithmetic."""
import re
from decimal import Decimal

INTRO = "Assalomu alaykum.\nSizning essengiz Sardor Toshmuhammadov tomonidan UZBMB baholash mezonlari asosida tekshirildi."
CRITERIA = (
    "Publitsistik uslub", "Qarashlar va shaxsiy fikr", "Dalillash",
    "Kirish–asosiy qism–xulosa", "Matn qurilishi va xatboshilar",
    "Izchillik va takror", "Imlo", "Punktuatsiya", "Qo‘shimcha qo‘llash",
    "So‘z qo‘llash uslubiyati", "Leksik boylik", "Nutq sofligi",
)
# Literal transcription of the supplied matrix, indexed by half-point units.
SCALE = (0, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42,
         43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58,
         59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75)
STOP_SCORES = {"mavzuga mos emas": 2, "100 so‘zdan kam": 2, "ko‘chirilgan": 2,
               "esse yo‘q": 0, "faqat kirish": 0, "to‘liq kirill": 0}
RECOMMENDATIONS = "BALLNI OSHIRISH UCHUN TAVSIYALAR (5 ta):"
CONCLUSION = "UMUMIY XULOSA:"


def scale_score(score) -> int:
    units = Decimal(str(score)) * 2
    if units != units.to_integral_value() or not 0 <= units <= 48:
        raise ValueError("Invalid total")
    return SCALE[int(units)]


def totals(score) -> str:
    return f"Jami ball: {score:g} / 24\n\n75 ballik shkala bo‘yicha: {scale_score(score)} / 75"


def validate_result(text: str, essay: str) -> str:
    text = text.strip()
    if not text.startswith(INTRO) or "MATN BO‘YICHA IZOHLAR" in text:
        raise ValueError("Invalid result sections")
    body = text[len(INTRO):].strip()
    total_pattern = r"Jami ball: ([0-9]+(?:\.5)?) / 24\s+75 ballik shkala bo‘yicha: ([0-9]+) / 75"
    if body.startswith("STOP NATIJA:"):
        match = re.fullmatch(r"STOP NATIJA:\s+Sabab: ([^\n]+)\s+" + total_pattern, body)
        if not match or match[1].strip() not in STOP_SCORES:
            raise ValueError("Invalid STOP result")
        reason = match[1].strip()
        score = STOP_SCORES[reason]
        if Decimal(match[2]) != score or int(match[3]) != scale_score(score):
            raise ValueError("Invalid STOP arithmetic")
        return INTRO + "\n\nSTOP NATIJA:\n\nSabab: " + reason + "\n\n" + totals(score)
    if len(essay.split()) < 100:
        raise ValueError("Short essay requires official STOP result")
    pattern = r"BAHOLASH NATIJALARI:\s+"
    for name in CRITERIA:
        pattern += re.escape(name) + r" — (0|0\.5|1|1\.5|2)\s+"
    pattern += total_pattern + r"\s+" + re.escape(RECOMMENDATIONS) + r"\s+(.+?)\s+" + re.escape(CONCLUSION) + r"\s+(.+)"
    match = re.fullmatch(pattern, body, re.S)
    if not match:
        raise ValueError("Malformed rubric result")
    scores = [Decimal(match[i]) for i in range(1, 13)]
    total = sum(scores)
    if Decimal(match[13]) != total or int(match[14]) != scale_score(total):
        raise ValueError("Invalid score arithmetic")
    recommendations, conclusion = match[15].strip(), match[16].strip()
    items = re.findall(r"(?m)^(\d+)\.\s+", recommendations)
    if items != ["1", "2", "3", "4", "5"] or "Qisqasi, maslahatim" not in conclusion:
        raise ValueError("Invalid recommendations or closing")
    if any(not part.strip() for part in re.split(r"(?m)^\d+\.\s+", recommendations)[1:]):
        raise ValueError("Empty recommendation")
    if any(x in recommendations + conclusion for x in ("BAHOLASH NATIJALARI:", "STOP NATIJA:", "Kirish qismi:", "Asosiy qism:", "Imlo:", "Punktuatsiya:")):
        raise ValueError("Unexpected extra section")
    return (INTRO + "\n\nBAHOLASH NATIJALARI:\n\n" +
            "\n\n".join(f"{name} — {score:g}" for name, score in zip(CRITERIA, scores)) +
            "\n\n" + totals(total) + "\n\n" + RECOMMENDATIONS + "\n\n" +
            recommendations + "\n\n" + CONCLUSION + "\n\n" + conclusion)


def split_result(text: str, limit: int = 3900) -> list[str]:
    """Split on paragraphs, then words; conservatively count UTF-16 units."""
    def size(value):
        return len(value.encode("utf-16-le")) // 2
    parts, current = [], ""
    for paragraph in text.split("\n\n"):
        addition = ("\n\n" if current else "") + paragraph
        if size(current + addition) <= limit:
            current += addition
            continue
        if current:
            parts.append(current)
            current = ""
        while size(paragraph) > limit:
            end, units = 0, 0
            for char in paragraph:
                if units + size(char) > limit:
                    break
                units += size(char)
                end += 1
            boundary = paragraph.rfind(" ", 0, end)
            if boundary > end // 2:
                end = boundary
            parts.append(paragraph[:end])
            paragraph = paragraph[end:].lstrip()
        current = paragraph
    if current:
        parts.append(current)
    return parts
