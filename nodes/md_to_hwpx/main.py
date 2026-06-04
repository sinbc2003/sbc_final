"""
마크다운 → HWPX 변환 노드.

구현 우선순위:
1. pypandoc-hwpx CLI (설치되어 있으면)
2. kordoc CLI
3. 내장 HWPX 빌더 (fallback — 서식/표병합/수식 지원)

HWPX = ZIP 안에 XML들이 들어있는 구조.

내장 빌더 지원 기능:
  - 헤딩 (h1-h6)
  - 인라인 서식 (**bold**, *italic*)
  - 표 (colspan/rowspan: > 또는 빈셀=오른쪽 병합, ^=아래 병합)
  - 수식 ($...$, $$...$$) → HWP 수식 스크립트
  - 리스트 (·/-)
  - 복수 폰트, charPr, paraPr
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

# 수식 변환기 임포트
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from engine.hwpml.equation import latex_to_hwp, hwp_equation_to_xml
    _EQ_AVAILABLE = True
except ImportError:
    _EQ_AVAILABLE = False


# ── HWPX 템플릿 (한컴오피스 실제 구조 기반) ──────────

NS = "http://www.hancom.co.kr/hwpml/2011"
ALL_NS = (
    f'xmlns:ha="{NS}/app" xmlns:hp="{NS}/paragraph" '
    f'xmlns:hs="{NS}/section" xmlns:hc="{NS}/core" '
    f'xmlns:hh="{NS}/head" xmlns:hm="{NS}/master-page"'
)

MIMETYPE = "application/hwp+zip"

VERSION_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    f'<hv:HCFVersion xmlns:hv="{NS}/version" '
    'tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="0" '
    'buildNumber="1" os="1" xmlVersion="1.2" '
    'application="TeacherFlow" appVersion="0, 1, 0, 0 WIN32LEWindows_8"/>'
)

CONTAINER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">'
    '<ocf:rootfiles>'
    '<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
    '</ocf:rootfiles></ocf:container>'
)

MANIFEST_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
)

SETTINGS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    f'<ha:HWPApplicationSetting xmlns:ha="{NS}/app" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">'
    '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>'
    '</ha:HWPApplicationSetting>'
)

CONTENT_HPF = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    f'<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" {ALL_NS} '
    'version="" unique-identifier="" id="">'
    '<opf:metadata><opf:title>TeacherFlow</opf:title>'
    '<opf:language>ko</opf:language></opf:metadata>'
    '<opf:manifest>'
    '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
    '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
    '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>'
    '</opf:manifest>'
    '<opf:spine>'
    '<opf:itemref idref="header" linear="yes"/>'
    '<opf:itemref idref="section0" linear="yes"/>'
    '</opf:spine></opf:package>'
)

# ── charPr ID 상수 ──
CHAR_NORMAL = 0      # 본문 10pt
CHAR_H1 = 1          # h1 22pt bold
CHAR_H2 = 2          # h2 16pt bold
CHAR_H3 = 3          # h3 13pt bold
CHAR_H4 = 4          # h4 11pt bold
CHAR_BOLD = 5        # 본문 bold
CHAR_ITALIC = 6      # 본문 italic
CHAR_BOLD_ITALIC = 7 # 본문 bold+italic
CHAR_TABLE_HEADER = 8  # 표 헤더 10pt bold
CHAR_EQ = 9          # 수식용

# ── paraPr ID 상수 ──
PARA_JUSTIFY = 0
PARA_CENTER = 1
PARA_LEFT = 2
PARA_RIGHT = 3

# ── borderFill ID ──
BF_NONE = 0
BF_TABLE_DEFAULT = 1
BF_TABLE_HEADER = 2


def _build_header_xml() -> str:
    """동적 header.xml 생성 — 복수 폰트, 풍부한 charPr/paraPr."""
    fonts = [
        ('\ud568\ucd08\ub86c\ub3cb\uc6c0', 'TTF'),    # 0: 함초롬돋움
        ('\ub9d1\uc740 \uace0\ub515', 'TTF'),          # 1: 맑은 고딕
    ]

    # charPr 정의: (id, fontRef, fontSz, bold, italic)
    char_defs = [
        (CHAR_NORMAL,       0, 1000, False, False),
        (CHAR_H1,           0, 2200, True,  False),
        (CHAR_H2,           0, 1600, True,  False),
        (CHAR_H3,           0, 1300, True,  False),
        (CHAR_H4,           0, 1100, True,  False),
        (CHAR_BOLD,         0, 1000, True,  False),
        (CHAR_ITALIC,       0, 1000, False, True),
        (CHAR_BOLD_ITALIC,  0, 1000, True,  True),
        (CHAR_TABLE_HEADER, 0, 1000, True,  False),
        (CHAR_EQ,           0, 1000, False, False),
    ]

    # fontfaces
    ff_parts = []
    for lang in ('HANGUL', 'LATIN', 'HANJA'):
        entries = ''.join(
            f'<hh:font face="{face}" type="{ftype}"/>'
            for face, ftype in fonts
        )
        ff_parts.append(f'<hh:fontface lang="{lang}">{entries}</hh:fontface>')
    fontfaces = f'<hh:fontfaces>{"".join(ff_parts)}</hh:fontfaces>'

    # charProperties
    cp_parts = []
    for cid, fref, sz, bold, italic in char_defs:
        inner = f'<hh:fontRef hangul="{fref}" latin="{fref}" hanja="{fref}"/>'
        inner += f'<hh:fontSz val="{sz}"/>'
        if bold:
            inner += '<hh:bold/>'
        if italic:
            inner += '<hh:italic/>'
        cp_parts.append(f'<hh:charPr id="{cid}">{inner}</hh:charPr>')
    char_props = f'<hh:charProperties>{"".join(cp_parts)}</hh:charProperties>'

    # paraProperties
    pp_parts = [
        f'<hh:paraPr id="{PARA_JUSTIFY}"><hh:align val="JUSTIFY"/></hh:paraPr>',
        f'<hh:paraPr id="{PARA_CENTER}"><hh:align val="CENTER"/></hh:paraPr>',
        f'<hh:paraPr id="{PARA_LEFT}"><hh:align val="LEFT"/></hh:paraPr>',
        f'<hh:paraPr id="{PARA_RIGHT}"><hh:align val="RIGHT"/></hh:paraPr>',
    ]
    para_props = f'<hh:paraProperties>{"".join(pp_parts)}</hh:paraProperties>'

    # borderFills
    bf_parts = [
        f'<hh:borderFill id="{BF_NONE}"/>',
        (f'<hh:borderFill id="{BF_TABLE_DEFAULT}">'
         '<hh:slash/><hh:border><hh:left type="SOLID" width="0.12mm"/>'
         '<hh:right type="SOLID" width="0.12mm"/>'
         '<hh:top type="SOLID" width="0.12mm"/>'
         '<hh:bottom type="SOLID" width="0.12mm"/>'
         '</hh:border></hh:borderFill>'),
        (f'<hh:borderFill id="{BF_TABLE_HEADER}">'
         '<hh:slash/><hh:border><hh:left type="SOLID" width="0.12mm"/>'
         '<hh:right type="SOLID" width="0.12mm"/>'
         '<hh:top type="SOLID" width="0.12mm"/>'
         '<hh:bottom type="SOLID" width="0.12mm"/>'
         '</hh:border>'
         '<hh:fillBrush><hh:windowBrush faceColor="#E6E6E6"/></hh:fillBrush>'
         '</hh:borderFill>'),
    ]
    border_fills = f'<hh:borderFills>{"".join(bf_parts)}</hh:borderFills>'

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<hh:head {ALL_NS}>'
        '<hh:beginNum page="1" footnote="1" endnote="1"/>'
        f'<hh:refList>{fontfaces}{char_props}{para_props}{border_fills}</hh:refList>'
        '</hh:head>'
    )


HEADER_XML = _build_header_xml()


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _parse_inline(text: str) -> str:
    """인라인 마크다운 서식 → HWPX run XML.

    **bold**, *italic*, ***bold+italic***, $수식$, $$블록수식$$
    """
    runs = []
    pos = 0
    n = len(text)

    while pos < n:
        # $$블록 수식$$ (인라인 컨텍스트에서도 처리)
        if text[pos:pos + 2] == '$$':
            end = text.find('$$', pos + 2)
            if end != -1:
                latex = text[pos + 2:end]
                if _EQ_AVAILABLE:
                    hwp_eq = latex_to_hwp(latex)
                    runs.append(
                        f'<hp:equation version="2.0"><hp:script>'
                        f'{_escape_xml(hwp_eq)}</hp:script></hp:equation>'
                    )
                else:
                    runs.append(f'<hp:run charPrIDRef="{CHAR_EQ}"><hp:t>{_escape_xml(latex)}</hp:t></hp:run>')
                pos = end + 2
                continue

        # $인라인 수식$
        if text[pos] == '$' and (pos + 1 < n and text[pos + 1] != '$'):
            end = text.find('$', pos + 1)
            if end != -1:
                latex = text[pos + 1:end]
                if _EQ_AVAILABLE:
                    hwp_eq = latex_to_hwp(latex)
                    runs.append(
                        f'<hp:equation version="2.0"><hp:script>'
                        f'{_escape_xml(hwp_eq)}</hp:script></hp:equation>'
                    )
                else:
                    runs.append(f'<hp:run charPrIDRef="{CHAR_EQ}"><hp:t>{_escape_xml(latex)}</hp:t></hp:run>')
                pos = end + 1
                continue

        # ***bold+italic***
        m = re.match(r'\*\*\*(.+?)\*\*\*', text[pos:])
        if m:
            runs.append(f'<hp:run charPrIDRef="{CHAR_BOLD_ITALIC}"><hp:t>{_escape_xml(m.group(1))}</hp:t></hp:run>')
            pos += m.end()
            continue

        # **bold**
        m = re.match(r'\*\*(.+?)\*\*', text[pos:])
        if m:
            runs.append(f'<hp:run charPrIDRef="{CHAR_BOLD}"><hp:t>{_escape_xml(m.group(1))}</hp:t></hp:run>')
            pos += m.end()
            continue

        # *italic*
        m = re.match(r'\*(.+?)\*', text[pos:])
        if m:
            runs.append(f'<hp:run charPrIDRef="{CHAR_ITALIC}"><hp:t>{_escape_xml(m.group(1))}</hp:t></hp:run>')
            pos += m.end()
            continue

        # 일반 텍스트 구간 (다음 특수 문자까지)
        end = pos + 1
        while end < n and text[end] not in ('*', '$'):
            end += 1
        chunk = text[pos:end]
        if chunk:
            runs.append(f'<hp:run charPrIDRef="{CHAR_NORMAL}"><hp:t>{_escape_xml(chunk)}</hp:t></hp:run>')
        pos = end

    return ''.join(runs)


def _md_to_section_xml(md_text: str) -> str:
    """마크다운 → section0.xml 내용."""
    lines = md_text.split("\n")
    paragraphs = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # 헤딩 (h1-h6)
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2).strip()
            char_id = min(level, CHAR_H4)  # h5,h6 → h4 스타일 사용
            inner = _parse_inline(text)
            # 첫 run의 charPr를 헤딩으로 오버라이드
            inner = re.sub(
                r'charPrIDRef="\d+"',
                f'charPrIDRef="{char_id}"',
                inner, count=1,
            )
            paragraphs.append(f'<hp:p paraPrIDRef="{PARA_LEFT}">{inner}</hp:p>')
            i += 1
            continue

        # $$블록 수식$$
        if line.strip().startswith('$$'):
            eq_lines = [line]
            if not line.strip().endswith('$$') or line.strip() == '$$':
                i += 1
                while i < len(lines):
                    eq_lines.append(lines[i])
                    if '$$' in lines[i] and lines[i].strip() != '$$':
                        break
                    if lines[i].strip() == '$$':
                        break
                    i += 1
            latex = '\n'.join(eq_lines)
            latex = re.sub(r'^\$\$|\$\$$', '', latex.strip()).strip()
            if _EQ_AVAILABLE and latex:
                hwp_eq = latex_to_hwp(latex)
                paragraphs.append(
                    f'<hp:p paraPrIDRef="{PARA_CENTER}">'
                    f'<hp:equation version="2.0"><hp:script>'
                    f'{_escape_xml(hwp_eq)}</hp:script></hp:equation>'
                    f'</hp:p>'
                )
            elif latex:
                paragraphs.append(
                    f'<hp:p paraPrIDRef="{PARA_CENTER}">'
                    f'<hp:run charPrIDRef="{CHAR_EQ}"><hp:t>{_escape_xml(latex)}</hp:t></hp:run>'
                    f'</hp:p>'
                )
            i += 1
            continue

        # 구분선
        if re.match(r"^---+\s*$", line):
            i += 1
            continue

        # HTML 주석
        if line.strip().startswith("<!--"):
            i += 1
            continue

        # 빈 줄
        if not line.strip():
            i += 1
            continue

        # 표 (| ... | 형식)
        if "|" in line and re.match(r"^\|.*\|$", line.strip()):
            table_lines = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                table_lines.append(lines[i])
                i += 1
            table_xml = _table_to_xml(table_lines)
            if table_xml:
                paragraphs.append(table_xml)
            continue

        # 리스트
        list_match = re.match(r"^(\s*)([-*·]|\d+\.)\s+(.+)$", line)
        if list_match:
            indent = len(list_match.group(1))
            marker = list_match.group(2)
            text = list_match.group(3).strip()
            prefix = f"{marker} " if marker in ('-', '*', '·') else f"{marker} "
            inner = _parse_inline(text)
            paragraphs.append(
                f'<hp:p paraPrIDRef="{PARA_LEFT}">'
                f'<hp:run charPrIDRef="{CHAR_NORMAL}"><hp:t>{_escape_xml(prefix)}</hp:t></hp:run>'
                f'{inner}'
                f'</hp:p>'
            )
            i += 1
            continue

        # 일반 단락
        text = line.strip()
        inner = _parse_inline(text)
        paragraphs.append(
            f'<hp:p paraPrIDRef="{PARA_JUSTIFY}">{inner}</hp:p>'
        )
        i += 1

    body = "\n".join(paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<hs:sec {ALL_NS}>'
        '<hp:secPr>'
        '<hp:pageMargin left="8504" right="8504" top="5668" bottom="4252" '
        'header="4252" footer="4252" gutter="0"/>'
        '<hp:pageSz width="59528" height="84188"/>'
        '</hp:secPr>'
        f'{body}'
        '</hs:sec>'
    )


def _parse_table_alignment(separator_line: str) -> List[str]:
    """구분선에서 정렬 정보 추출."""
    cells = [c.strip() for c in separator_line.strip().strip("|").split("|")]
    aligns = []
    for c in cells:
        if c.startswith(':') and c.endswith(':'):
            aligns.append('CENTER')
        elif c.endswith(':'):
            aligns.append('RIGHT')
        else:
            aligns.append('LEFT')
    return aligns


def _table_to_xml(table_lines: list[str]) -> str:
    """마크다운 표 → HWPX 표 XML.

    병합 규칙:
      - 셀 내용이 '>' 또는 빈 문자열이고 왼쪽 셀 존재 → colspan (오른쪽 병합)
      - 셀 내용이 '^' → rowspan (아래 병합)
    """
    raw_rows = []
    aligns = []
    is_header_row = []

    for idx, line in enumerate(table_lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # 구분선 → 정렬 정보 추출
        if all(re.match(r"^[-:]+$", c) for c in cells if c):
            aligns = _parse_table_alignment(line)
            continue
        raw_rows.append(cells)
        is_header_row.append(idx == 0 and len(table_lines) > 1)

    if not raw_rows:
        return ""

    num_cols = max(len(r) for r in raw_rows)
    num_rows = len(raw_rows)
    # 패딩
    for r in raw_rows:
        while len(r) < num_cols:
            r.append("")
    while len(aligns) < num_cols:
        aligns.append('LEFT')

    # ── 병합 맵 계산 ──
    # grid[r][c] = {"text": str, "colspan": int, "rowspan": int, "skip": bool}
    grid = []
    for r in range(num_rows):
        row = []
        for c in range(num_cols):
            row.append({
                "text": raw_rows[r][c],
                "colspan": 1,
                "rowspan": 1,
                "skip": False,
            })
        grid.append(row)

    # colspan: '>' 또는 왼쪽 셀과 병합되는 빈 셀
    for r in range(num_rows):
        for c in range(num_cols - 1, 0, -1):
            if grid[r][c]["text"] in ('>', ''):
                # 왼쪽 셀이 skip이 아닌 첫 번째 셀 찾기
                left = c - 1
                while left >= 0 and grid[r][left]["skip"]:
                    left -= 1
                if left >= 0 and grid[r][left]["text"] not in ('>', '^', ''):
                    grid[r][left]["colspan"] += 1
                    grid[r][c]["skip"] = True
                elif grid[r][c]["text"] == '>':
                    # 명시적 > 마커는 항상 병합
                    if left >= 0:
                        grid[r][left]["colspan"] += 1
                        grid[r][c]["skip"] = True

    # rowspan: '^' 마커
    for r in range(num_rows - 1, 0, -1):
        for c in range(num_cols):
            if grid[r][c]["text"] == '^' and not grid[r][c]["skip"]:
                # 위쪽에서 skip이 아닌 가장 가까운 셀 찾기
                above = r - 1
                while above >= 0 and grid[above][c]["skip"]:
                    above -= 1
                if above >= 0:
                    grid[above][c]["rowspan"] += 1
                    grid[r][c]["skip"] = True

    # ── XML 생성 ──
    col_width = 59528 // num_cols
    row_height = 1200

    row_xmls = []
    for r in range(num_rows):
        cell_xmls = []
        for c in range(num_cols):
            cell = grid[r][c]
            if cell["skip"]:
                continue

            text = cell["text"]
            colspan = cell["colspan"]
            rowspan = cell["rowspan"]
            is_header = r == 0 and is_header_row[r] if r < len(is_header_row) else False
            char_id = CHAR_TABLE_HEADER if is_header else CHAR_NORMAL
            bf_id = BF_TABLE_HEADER if is_header else BF_TABLE_DEFAULT
            align = aligns[c] if c < len(aligns) else 'LEFT'
            para_id = {'CENTER': PARA_CENTER, 'RIGHT': PARA_RIGHT}.get(align, PARA_LEFT)

            # 셀 XML
            cell_xml = f'<hp:tc>'
            cell_xml += f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/>'
            cell_xml += f'<hp:cellSz width="{col_width * colspan}" height="{row_height * rowspan}"/>'
            if colspan > 1:
                cell_xml += f'<hp:cellSpan colSpan="{colspan}"/>'
            if rowspan > 1:
                cell_xml += f'<hp:cellSpan rowSpan="{rowspan}"/>'
            cell_xml += f'<hp:cellBorderFill borderFillIDRef="{bf_id}"/>'

            # 셀 내 텍스트 (인라인 서식 지원)
            if text and text not in ('>', '^'):
                inner = _parse_inline(text)
                # charPr 오버라이드 (헤더행)
                if is_header:
                    inner = re.sub(
                        r'charPrIDRef="\d+"',
                        f'charPrIDRef="{char_id}"',
                        inner,
                    )
                cell_xml += f'<hp:p paraPrIDRef="{para_id}">{inner}</hp:p>'
            else:
                cell_xml += f'<hp:p paraPrIDRef="{para_id}"><hp:run charPrIDRef="{char_id}"><hp:t></hp:t></hp:run></hp:p>'

            cell_xml += '</hp:tc>'
            cell_xmls.append(cell_xml)

        row_xmls.append(f'<hp:tr>{"".join(cell_xmls)}</hp:tr>')

    return (
        f'<hp:tbl>'
        f'<hp:tblPr cols="{num_cols}" borderFillIDRef="{BF_TABLE_DEFAULT}"/>'
        f'{"".join(row_xmls)}'
        f'</hp:tbl>'
    )


def _build_hwpx(md_text: str, output_path: str) -> str:
    """마크다운에서 HWPX 파일 직접 생성 (한컴오피스 호환)."""
    section_xml = _md_to_section_xml(md_text)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype은 비압축 + 첫 번째 (ODF/HWPX 표준)
        zf.writestr("mimetype", MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("version.xml", VERSION_XML, compress_type=zipfile.ZIP_STORED)
        zf.writestr("Contents/header.xml", HEADER_XML)
        zf.writestr("Contents/section0.xml", section_xml)
        zf.writestr("Contents/content.hpf", CONTENT_HPF)
        zf.writestr("settings.xml", SETTINGS_XML)
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("META-INF/manifest.xml", MANIFEST_XML)

    return output_path


def _convert_with_kordoc(md_text: str, output_path: str) -> str | None:
    """kordoc CLI로 변환 시도."""
    if not shutil.which("npx"):
        return None

    try:
        # 임시 파일에 마크다운 저장
        md_tmp = output_path + ".tmp.md"
        with open(md_tmp, "w", encoding="utf-8") as f:
            f.write(md_text)

        cmd = ["npx", "kordoc", "md-to-hwpx", md_tmp, "-o", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        os.unlink(md_tmp)

        if result.returncode == 0 and Path(output_path).exists():
            return output_path
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    return None


def _preprocess_md_for_hwpx(md_text: str) -> str:
    """마크다운 전처리 — pypandoc-hwpx 알려진 버그 회피.

    참고: github.com/msjang/pypandoc-hwpx/issues/1
    """
    # 1. 빈 표 셀 → 마침표 삽입 (한/글 크래시 방지)
    md_text = re.sub(r'\|(\s*)\|', '| . |', md_text)

    # 2. 리스트 마커 → 가운뎃점 (1pt 렌더링 버그 회피)
    md_text = re.sub(r'^- ', '· ', md_text, flags=re.MULTILINE)

    # 3. 직선 따옴표 → 유니코드 꺾은따옴표 (텍스트 소실 방지)
    # 큰따옴표: 열림/닫힘 번갈아
    result = []
    in_double = False
    in_single = False
    for ch in md_text:
        if ch == '"':
            result.append('\u201c' if not in_double else '\u201d')
            in_double = not in_double
        elif ch == "'":
            result.append('\u2018' if not in_single else '\u2019')
            in_single = not in_single
        else:
            result.append(ch)
    md_text = ''.join(result)

    # 4. SMP 이모지 제거 (한/글 XML 파서 한계)
    md_text = re.sub(r'[\U00010000-\U0010FFFF]', '', md_text)

    return md_text


def _convert_with_pypandoc_hwpx(md_text: str, output_path: str) -> str | None:
    """pypandoc-hwpx로 변환 (Pandoc AST 기반, 가장 정확)."""
    try:
        import subprocess
        # 임시 md 파일 작성
        md_tmp = output_path + ".tmp.md"
        with open(md_tmp, "w", encoding="utf-8") as f:
            f.write(md_text)

        result = subprocess.run(
            ["pypandoc-hwpx", md_tmp, "-o", output_path],
            capture_output=True, text=True, timeout=120,
        )
        os.unlink(md_tmp)

        if result.returncode == 0 and Path(output_path).exists():
            return output_path
        # 에러 메시지
        err = (result.stderr or result.stdout or "").strip()
        if err:
            return None
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


def execute(inputs: dict, params: dict, context: dict) -> dict:
    md_text = inputs["텍스트"]
    output_name = params.get("output_name", "output")
    output_path = os.path.join(context["temp_dir"], f"{output_name}.hwpx")

    context["progress"](0.1)
    context["log"]("HWPX 변환 시작")

    # 전처리 (알려진 버그 회피)
    md_text = _preprocess_md_for_hwpx(md_text)

    # 1순위: pypandoc-hwpx (Pandoc AST 기반, 가장 정확)
    result = _convert_with_pypandoc_hwpx(md_text, output_path)
    if result:
        context["log"]("pypandoc-hwpx로 변환 완료")
        context["progress"](1.0)
        return {"파일": result}

    # 2순위: kordoc CLI
    context["log"]("pypandoc-hwpx 미설치, kordoc 시도")
    result = _convert_with_kordoc(md_text, output_path)
    if result:
        context["log"]("kordoc로 변환 완료")
        context["progress"](1.0)
        return {"파일": result}

    # 3순위: 내장 빌더 (최소 기능)
    context["log"]("외부 도구 없음, 내장 빌더로 변환 (제한된 서식)")
    result = _build_hwpx(md_text, output_path)

    context["progress"](1.0)
    context["log"](f"HWPX 생성 완료: {result}")

    return {"파일": result}
