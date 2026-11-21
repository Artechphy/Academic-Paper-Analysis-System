"""Shared formatting units and text recognition."""
import re
import unicodedata

CHINESE_FONT_SIZES = {"二号": 22.0, "小二号": 18.0, "小三号": 15.0,
                      "四号": 14.0, "小四号": 12.0, "五号": 10.5}
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ffff\U00030000-\U000323af]")
FONT_FAMILIES = {
    "simsun": ("simsun", "nsimsun", "songtisc", "stsong", "stsongti", "fangzhengshusong",
               "宋体", "华文宋体", "方正书宋", "新宋体", "宋體", "fzss", "fzshusong"),
    "simhei": ("simhei", "heitisc", "stheiti", "heiti", "黑体", "黑體", "华文黑体"),
    "times_new_roman": ("timesnewromanps", "timesnewroman", "timesroman", "times"),
    "microsoft_yahei": ("microsoftyahei", "微软雅黑", "微軟雅黑"),
}
FONT_SUFFIX = re.compile(r"(?:psmt|ps|mt|std|regular|roman|light|book|bold|italic|oblique|medium|semibold|demibold|heavy|black)+$")
ROMAN = re.compile(r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})", re.I)
CHAPTER = re.compile(r"^第\s*([一二三四五六七八九十百零〇两\d]+)\s*章[\s、.：:]*\S")
SECTION_HEADINGS = (
    ("declaration", r"(?:学位论文|论文)?(?:独创性|原创性)(?:声明)?(?:(?:和|与|及)(?:学位论文)?使用授权(?:书|声明)|声明)?|(?:学位论文)?使用授权(?:书|声明)"),
    ("defense_signature", r"(?:学位论文)?答辩(?:委员会)?签名表"),
    ("abstract_cn", r"(?:中文)?摘要"),
    ("abstract_en", r"abstract"),
    ("toc", r"目录|contents|tableofcontents"),
    ("introduction", r"绪论|引言|前言|introduction"),
    ("body", r"正文|maintext|材料与方法|研究方法|结果与(?:分析|讨论)|methods|results(?:anddiscussion)?|discussion"),
    ("conclusion", r"结论(?:与展望)?|总结(?:与展望)?|conclusions?"),
    ("appendix", r"(?:附录|appendix)(?:[A-Z0-9一二三四五六七八九]+(?:\s+.*)?)?"),
    ("references", r"参考文献|references|bibliography"),
    ("achievements", r"(?:攻读(?:学位|硕士|博士|硕士学位|博士学位)期间)?(?:取得|发表)?(?:的)?(?:科研|研究|学术)成果"),
    ("acknowledgements", r"致谢|acknowledg(?:e)?ments"),
    ("resume", r"(?:作者)?个人简历|作者简历"),
)
SECTION_NAMES = dict(zip(
    ("cover", *(key for key, _ in SECTION_HEADINGS)),
    ("封面", "独创性和使用授权声明", "学位论文答辩签名表", "中文摘要", "英文摘要", "目录",
     "绪论", "正文", "结论", "附录", "参考文献", "攻读学位期间科研成果", "致谢", "个人简历"),
    strict=True,
))


def normalize_font_name(name: str | None) -> str | None:
    if not name:
        return None
    name = re.sub(r"^[A-Z]{6}\+", "", unicodedata.normalize("NFKC", name).strip(), flags=re.I)
    normalized = re.sub(r"[^\w]|_", "", name.casefold())
    for canonical, aliases in FONT_FAMILIES.items():
        if normalized == canonical.replace("_", "") or any(
            normalized == alias or normalized.startswith(alias) and FONT_SUFFIX.fullmatch(normalized[len(alias):])
            for alias in aliases
        ):
            return canonical
    # Some PostScript names carry vendor encoding suffixes (e.g. FZShuSong-Z01).
    if re.fullmatch(r"(?:fzss|fzshusong)[a-z]?\d+(?:s)?", normalized):
        return "simsun"
    return re.sub(r"[^\w]+", "_", name.casefold()).strip("_") or None


def pt_to_mm(points: float) -> float:
    return points * 25.4 / 72


def mm_to_pt(mm: float) -> float:
    return mm * 72 / 25.4


def chinese_size_to_pt(size: str) -> float:
    return CHINESE_FONT_SIZES[size]


def count_chinese_chars(text: str) -> int:
    return sum(1 for _ in HAN.finditer(text))


def page_number_format(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip()
    text = re.sub(r"^第\s*(.+?)\s*页$", r"\1", text).strip(" —–-")
    if re.fullmatch(r"[0-9]+", text):
        return "decimal"
    if text and ROMAN.fullmatch(text):
        return "roman"
    return "none"


def chapter_number(text: str) -> int | None:
    match = CHAPTER.match(unicodedata.normalize("NFKC", text).strip())
    if not match:
        return None
    number = match[1]
    if number.isdecimal():
        return int(number)
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    if not any(unit in number for unit in "十百"):
        return int("".join(str(digits[char]) for char in number))
    result = digit = 0
    for char in number:
        if char in "十百":
            result += (digit or 1) * {"十": 10, "百": 100}[char]
            digit = 0
        else:
            digit = digits[char]
    return result + digit


def heading_key(text: str) -> str | None:
    text = unicodedata.normalize("NFKC", text).strip()
    prefix = re.match(r"^第\s*[一二三四五六七八九十百零〇两\d]+\s*章[\s、.：:]*", text)
    if prefix:
        text = text[prefix.end():]
    text = re.sub(r"^(?:[一二三四五六七八九十]+[、.]\s*|\d+(?:[、.]\s*|\s+))", "", text)
    for key, pattern in SECTION_HEADINGS:
        candidate = text if key == "appendix" else re.sub(r"[\s、:：]+", "", text)
        if re.fullmatch(pattern, candidate, re.I):
            return key
    return None


def heading_level(text: str, style: str | None = None) -> int | None:
    if style:
        match = re.search(r"(?:heading|标题)\s*([1-4])\b", style, re.I)
        if match:
            return int(match[1])
    text = unicodedata.normalize("NFKC", text).strip()
    if CHAPTER.match(text):
        return 1
    match = re.match(r"^(\d+(?:\.\d+){1,3})[.、\s]+\s*\S", text)
    if match:
        return match[1].count(".") + 1
    if re.match(r"^第[一二三四五六七八九十\d]+节\s*\S", text):
        return 2
    if re.match(r"^[一二三四五六七八九十]+、\s*\S", text):
        return 3
    if re.match(r"^\([一二三四五六七八九十\d]+\)\s*\S", text):
        return 4
    return None
