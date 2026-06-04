"""
LaTeX → HWP 수식 변환기.

한/글 수식 편집기는 LaTeX와 유사하지만 고유한 문법을 사용.
이 모듈은 LaTeX 수학 표현을 한/글 수식 스크립트로 변환.

주요 변환:
  \\frac{a}{b}          → a over b
  \\sqrt{x}             → sqrt {x}
  \\sum_{i=1}^{n}       → sum from {i=1} to {n}
  \\int_0^\\infty        → int from {0} to {inf}
  \\lim_{x\\to 0}        → lim from {x -> 0}
  \\begin{pmatrix}...   → matrix { ... }
  \\begin{cases}...     → cases { ... }

Markdown 연동:
  $...$    → 인라인 수식
  $$...$$  → 블록 수식

참조: 09_HWPML_구조_분석.md §4 수식 문법
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple


# ── LaTeX → HWP 명령 매핑 ────────────────────────────

# 그리스 문자
_GREEK_MAP = {
    r'\alpha': 'alpha', r'\beta': 'beta', r'\gamma': 'gamma',
    r'\delta': 'delta', r'\epsilon': 'epsilon', r'\varepsilon': 'varepsilon',
    r'\zeta': 'zeta', r'\eta': 'eta', r'\theta': 'theta',
    r'\vartheta': 'vartheta', r'\iota': 'iota', r'\kappa': 'kappa',
    r'\lambda': 'lambda', r'\mu': 'mu', r'\nu': 'nu',
    r'\xi': 'xi', r'\pi': 'pi', r'\rho': 'rho',
    r'\sigma': 'sigma', r'\tau': 'tau', r'\upsilon': 'upsilon',
    r'\phi': 'phi', r'\varphi': 'varphi', r'\chi': 'chi',
    r'\psi': 'psi', r'\omega': 'omega',
    # 대문자
    r'\Gamma': 'GAMMA', r'\Delta': 'DELTA', r'\Theta': 'THETA',
    r'\Lambda': 'LAMBDA', r'\Xi': 'XI', r'\Pi': 'PI',
    r'\Sigma': 'SIGMA', r'\Upsilon': 'UPSILON', r'\Phi': 'PHI',
    r'\Psi': 'PSI', r'\Omega': 'OMEGA',
}

# 특수 기호
_SYMBOL_MAP = {
    r'\infty': 'inf', r'\infinity': 'inf',
    r'\pm': '±', r'\mp': '∓',
    r'\times': '×', r'\cdot': '·', r'\div': '÷',
    r'\leq': '≤', r'\le': '≤', r'\geq': '≥', r'\ge': '≥',
    r'\neq': '≠', r'\ne': '≠', r'\approx': '≈',
    r'\equiv': '≡', r'\sim': '~', r'\simeq': '≃',
    r'\propto': '∝',
    r'\in': '∈', r'\notin': '∉', r'\ni': '∋',
    r'\subset': '⊂', r'\supset': '⊃', r'\subseteq': '⊆', r'\supseteq': '⊇',
    r'\cup': '∪', r'\cap': '∩', r'\emptyset': '∅',
    r'\forall': '∀', r'\exists': '∃',
    r'\nabla': '∇', r'\partial': 'partial',
    r'\therefore': '∴', r'\because': '∵',
    r'\angle': '∠', r'\perp': '⊥', r'\parallel': '∥',
    r'\rightarrow': ' -> ',  r'\to': ' -> ', r'\Rightarrow': ' => ',
    r'\leftarrow': ' <- ', r'\Leftarrow': ' <= ',
    r'\leftrightarrow': ' <-> ', r'\Leftrightarrow': ' <=> ',
    r'\cdots': 'cdots', r'\ldots': '...', r'\vdots': 'vdots', r'\ddots': 'ddots',
    r'\quad': '~~', r'\qquad': '~~~~',
    r'\,': '~', r'\;': '~~', r'\!': '',
    r'\left': '', r'\right': '', r'\bigl': '', r'\bigr': '',
    r'\Bigl': '', r'\Bigr': '', r'\biggl': '', r'\biggr': '',
}

# 괄호
_BRACKET_MAP = {
    r'\langle': 'langle', r'\rangle': 'rangle',
    r'\lfloor': 'lfloor', r'\rfloor': 'rfloor',
    r'\lceil': 'lceil', r'\rceil': 'rceil',
    r'\lvert': '|', r'\rvert': '|',
    r'\lVert': '‖', r'\rVert': '‖',
}

# 함수 이름 (HWP에서 그대로 사용)
_FUNC_NAMES = {
    'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
    'arcsin', 'arccos', 'arctan',
    'sinh', 'cosh', 'tanh', 'coth',
    'log', 'ln', 'exp', 'det', 'dim', 'ker', 'gcd',
    'max', 'min', 'sup', 'inf', 'arg',
}

# 악센트/장식
_ACCENT_MAP = {
    r'\hat': 'hat', r'\bar': 'bar', r'\vec': 'vec',
    r'\dot': 'dot', r'\ddot': 'ddot',
    r'\tilde': 'tilde', r'\overline': 'overline',
    r'\underline': 'underline',
    r'\widehat': 'hat', r'\widetilde': 'tilde',
    r'\overrightarrow': 'vec',
}


# ── 내부 파서 ─────────────────────────────────────────

def _find_brace_group(text: str, start: int) -> Tuple[str, int]:
    """중괄호 그룹 추출. text[start]가 '{'일 때 호출.

    Returns: (내용 문자열, 닫는 '}' 다음 인덱스)
    """
    if start >= len(text) or text[start] != '{':
        return '', start
    depth = 0
    i = start
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    # 닫히지 않은 경우
    return text[start + 1:], len(text)


def _consume_next_token(text: str, pos: int) -> Tuple[str, int]:
    """다음 토큰 하나를 소비. '{...}' 그룹 또는 단일 문자/명령."""
    while pos < len(text) and text[pos] == ' ':
        pos += 1
    if pos >= len(text):
        return '', pos
    if text[pos] == '{':
        content, end = _find_brace_group(text, pos)
        return content, end
    if text[pos] == '\\':
        # 명령어 전체 소비
        j = pos + 1
        while j < len(text) and text[j].isalpha():
            j += 1
        return text[pos:j], j
    return text[pos], pos + 1


# ── 핵심 변환 함수 ───────────────────────────────────

def latex_to_hwp(latex: str) -> str:
    """LaTeX 수식 → HWP 수식 스크립트.

    Args:
        latex: LaTeX 수식 문자열 ($ 제거된 상태)

    Returns:
        한/글 수식 편집기 스크립트
    """
    result = _convert_inner(latex.strip())
    # 후처리: 연속 공백 정리
    result = re.sub(r' {2,}', ' ', result).strip()
    return result


_COMMANDS_WITH_ARGS = {
    r'\frac', r'\dfrac', r'\tfrac', r'\cfrac',
    r'\sqrt', r'\sum', r'\prod',
    r'\int', r'\iint', r'\iiint', r'\oint',
    r'\lim', r'\begin', r'\end',
    r'\text', r'\mathrm', r'\textrm', r'\textup',
    r'\mathbf', r'\mathit',
} | set(_ACCENT_MAP.keys())


def _convert_inner(tex: str) -> str:
    """재귀적 LaTeX → HWP 변환 (내부)."""
    out = []
    i = 0
    n = len(tex)

    while i < n:
        c = tex[i]

        # 공백
        if c in (' ', '\t', '\n'):
            if out and out[-1] != ' ':
                out.append(' ')
            i += 1
            continue

        # 주석
        if c == '%':
            # 줄 끝까지 스킵
            while i < n and tex[i] != '\n':
                i += 1
            continue

        # 그룹
        if c == '{':
            content, end = _find_brace_group(tex, i)
            converted = _convert_inner(content)
            out.append('{' + converted + '}')
            i = end
            continue

        # 위첨자/아래첨자 (HWP 동일)
        if c in ('^', '_'):
            out.append(c)
            i += 1
            token, i = _consume_next_token(tex, i)
            if '\\' in token or len(token) > 1:
                converted = _convert_inner(token)
                out.append('{' + converted + '}')
            else:
                out.append(token)
            continue

        # 백슬래시 명령
        if c == '\\':
            cmd_start = i
            i += 1
            if i >= n:
                break

            # \\ → 줄바꿈
            if tex[i] == '\\':
                out.append('##')
                i += 1
                continue

            # \{ \} \| 등 이스케이프
            if tex[i] in ('{', '}', '|', '&', '#', '%', '_'):
                out.append(tex[i])
                i += 1
                continue

            # 명령어 추출
            j = i
            while j < n and tex[j].isalpha():
                j += 1
            cmd = '\\' + tex[i:j]
            i = j

            # 인자를 받는 명령만 공백 건너뛰기
            if cmd in _COMMANDS_WITH_ARGS:
                while i < n and tex[i] == ' ':
                    i += 1

            # ── frac ──
            if cmd == r'\frac':
                num, i = _consume_next_token(tex, i)
                den, i = _consume_next_token(tex, i)
                num_c = _convert_inner(num)
                den_c = _convert_inner(den)
                out.append(f'{{{num_c}}} over {{{den_c}}}')
                continue

            # ── dfrac, tfrac → 동일하게 over ──
            if cmd in (r'\dfrac', r'\tfrac', r'\cfrac'):
                num, i = _consume_next_token(tex, i)
                den, i = _consume_next_token(tex, i)
                num_c = _convert_inner(num)
                den_c = _convert_inner(den)
                out.append(f'{{{num_c}}} over {{{den_c}}}')
                continue

            # ── sqrt ──
            if cmd == r'\sqrt':
                # 선택적 n-th root: \sqrt[n]{x}
                if i < n and tex[i] == '[':
                    end_bracket = tex.index(']', i)
                    root_n = tex[i + 1:end_bracket]
                    i = end_bracket + 1
                    body, i = _consume_next_token(tex, i)
                    body_c = _convert_inner(body)
                    root_c = _convert_inner(root_n)
                    out.append(f'{root_c} root {{{body_c}}}')
                else:
                    body, i = _consume_next_token(tex, i)
                    body_c = _convert_inner(body)
                    out.append(f'sqrt {{{body_c}}}')
                continue

            # ── sum, prod ──
            if cmd in (r'\sum', r'\prod'):
                hw_cmd = 'sum' if cmd == r'\sum' else 'prod'
                result = hw_cmd
                if i < n and tex[i] == '_':
                    i += 1
                    sub, i = _consume_next_token(tex, i)
                    result += f' from {{{_convert_inner(sub)}}}'
                    while i < n and tex[i] == ' ':
                        i += 1
                if i < n and tex[i] == '^':
                    i += 1
                    sup, i = _consume_next_token(tex, i)
                    result += f' to {{{_convert_inner(sup)}}}'
                out.append(result)
                continue

            # ── int, iint, iiint, oint ──
            if cmd in (r'\int', r'\iint', r'\iiint', r'\oint'):
                hw_cmd = cmd[1:]  # int, iint, iiint, oint 동일
                result = hw_cmd
                if i < n and tex[i] == '_':
                    i += 1
                    sub, i = _consume_next_token(tex, i)
                    result += f' from {{{_convert_inner(sub)}}}'
                    while i < n and tex[i] == ' ':
                        i += 1
                if i < n and tex[i] == '^':
                    i += 1
                    sup, i = _consume_next_token(tex, i)
                    result += f' to {{{_convert_inner(sup)}}}'
                out.append(result)
                continue

            # ── lim ──
            if cmd == r'\lim':
                result = 'lim'
                if i < n and tex[i] == '_':
                    i += 1
                    sub, i = _consume_next_token(tex, i)
                    sub_c = _convert_inner(sub)
                    # \to → ->
                    sub_c = sub_c.replace('to', '->')
                    result += f' from {{{sub_c}}}'
                out.append(result)
                continue

            # ── begin/end 환경 ──
            if cmd == r'\begin':
                env, i = _consume_next_token(tex, i)
                result, i = _handle_environment(tex, i, env)
                out.append(result)
                continue

            if cmd == r'\end':
                # \end{...} 건너뛰기 (begin에서 처리)
                _, i = _consume_next_token(tex, i)
                continue

            # ── 악센트/장식 ──
            if cmd in _ACCENT_MAP:
                hw_accent = _ACCENT_MAP[cmd]
                body, i = _consume_next_token(tex, i)
                body_c = _convert_inner(body)
                out.append(f'{hw_accent} {{{body_c}}}')
                continue

            # ── text, mathrm, mathbf 등 텍스트 명령 ──
            if cmd in (r'\text', r'\mathrm', r'\textrm', r'\textup'):
                body, i = _consume_next_token(tex, i)
                out.append(f'"{body}"')
                continue
            if cmd == r'\mathbf':
                body, i = _consume_next_token(tex, i)
                body_c = _convert_inner(body)
                out.append(f'bold {{{body_c}}}')
                continue
            if cmd == r'\mathit':
                body, i = _consume_next_token(tex, i)
                body_c = _convert_inner(body)
                out.append(f'ital {{{body_c}}}')
                continue

            # ── 그리스 문자 ──
            if cmd in _GREEK_MAP:
                out.append(_GREEK_MAP[cmd])
                continue

            # ── 특수 기호 ──
            if cmd in _SYMBOL_MAP:
                out.append(_SYMBOL_MAP[cmd])
                continue

            # ── 괄호 ──
            if cmd in _BRACKET_MAP:
                out.append(_BRACKET_MAP[cmd])
                continue

            # ── 함수 이름 ──
            func_name = cmd[1:]  # 백슬래시 제거
            if func_name in _FUNC_NAMES:
                out.append(func_name)
                continue

            # ── 알 수 없는 명령 → 그대로 전달 ──
            out.append(cmd[1:])
            continue

        # & → # (행렬/cases 열 구분)
        if c == '&':
            out.append('#')
            i += 1
            continue

        # 일반 문자
        out.append(c)
        i += 1

    return ''.join(out)


# ── 환경 처리 ─────────────────────────────────────────

def _handle_environment(tex: str, start: int, env: str) -> Tuple[str, int]:
    """LaTeX 환경 → HWP 수식.

    Returns: (hwp_script, end_pos)
    """
    # \end{env} 위치 찾기
    end_tag = f'\\end{{{env}}}'
    end_pos = tex.find(end_tag, start)
    if end_pos == -1:
        body = tex[start:]
        end_pos = len(tex)
    else:
        body = tex[start:end_pos]
        end_pos += len(end_tag)

    # 행렬 환경
    if env in ('pmatrix', 'bmatrix', 'vmatrix', 'Bmatrix', 'Vmatrix', 'matrix', 'array'):
        rows = body.split('\\\\')
        hwp_rows = []
        for row in rows:
            row = row.strip()
            if not row:
                continue
            cols = row.split('&')
            hwp_cols = [_convert_inner(c.strip()) for c in cols]
            hwp_rows.append(' # '.join(hwp_cols))
        inner = ' ## '.join(hwp_rows)

        # 괄호 선택
        if env == 'pmatrix':
            return f'left ( matrix {{{inner}}} right )', end_pos
        elif env == 'bmatrix':
            return f'left [ matrix {{{inner}}} right ]', end_pos
        elif env == 'vmatrix':
            return f'left | matrix {{{inner}}} right |', end_pos
        elif env == 'Bmatrix':
            return f'left {{ matrix {{{inner}}} right }}', end_pos
        elif env == 'Vmatrix':
            return f'left ‖ matrix {{{inner}}} right ‖', end_pos
        else:
            return f'matrix {{{inner}}}', end_pos

    # cases 환경
    if env == 'cases':
        rows = body.split('\\\\')
        hwp_rows = []
        for row in rows:
            row = row.strip()
            if not row:
                continue
            cols = row.split('&')
            hwp_cols = [_convert_inner(c.strip()) for c in cols]
            hwp_rows.append(' # '.join(hwp_cols))
        inner = ' ## '.join(hwp_rows)
        return f'cases {{{inner}}}', end_pos

    # aligned/align 환경
    if env in ('aligned', 'align', 'align*', 'gathered', 'gather', 'gather*'):
        rows = body.split('\\\\')
        hwp_rows = []
        for row in rows:
            row = row.strip()
            if not row:
                continue
            converted = _convert_inner(row)
            hwp_rows.append(converted)
        return ' ## '.join(hwp_rows), end_pos

    # 알 수 없는 환경 → 내용만 변환
    return _convert_inner(body), end_pos


# ── Markdown 수식 추출 ────────────────────────────────

def extract_equations_from_markdown(text: str) -> List[dict]:
    """마크다운에서 수식 추출.

    Returns:
        [{"type": "inline"|"block", "latex": str, "hwp": str, "start": int, "end": int}]
    """
    results = []

    # 블록 수식 ($$...$$) 먼저
    for m in re.finditer(r'\$\$(.*?)\$\$', text, re.DOTALL):
        results.append({
            "type": "block",
            "latex": m.group(1).strip(),
            "hwp": latex_to_hwp(m.group(1)),
            "start": m.start(),
            "end": m.end(),
        })

    # 인라인 수식 ($...$) — 블록 수식 범위 제외
    block_ranges = [(r["start"], r["end"]) for r in results]
    for m in re.finditer(r'(?<!\$)\$(?!\$)(.*?)\$(?!\$)', text):
        pos = m.start()
        if any(s <= pos < e for s, e in block_ranges):
            continue
        results.append({
            "type": "inline",
            "latex": m.group(1).strip(),
            "hwp": latex_to_hwp(m.group(1)),
            "start": m.start(),
            "end": m.end(),
        })

    results.sort(key=lambda x: x["start"])
    return results


def markdown_to_hwp_equations(text: str) -> str:
    """마크다운 텍스트의 수식을 HWP 수식으로 치환.

    $...$, $$...$$ → HWP 수식 스크립트로 변환.
    수식이 아닌 부분은 그대로 유지.
    """
    equations = extract_equations_from_markdown(text)
    if not equations:
        return text

    parts = []
    last_end = 0
    for eq in equations:
        parts.append(text[last_end:eq["start"]])
        if eq["type"] == "block":
            parts.append(f'[수식]{eq["hwp"]}[/수식]')
        else:
            parts.append(f'[수식]{eq["hwp"]}[/수식]')
        last_end = eq["end"]
    parts.append(text[last_end:])

    return ''.join(parts)


# ── HWPX 수식 XML 생성 ───────────────────────────────

def hwp_equation_to_xml(script: str, version: str = "2.0") -> str:
    """HWP 수식 스크립트 → HWPX XML 요소 문자열.

    HWPX의 <hp:equation> 요소를 생성.
    """
    # XML 이스케이프
    escaped = (script
               .replace('&', '&amp;')
               .replace('<', '&lt;')
               .replace('>', '&gt;'))
    return (
        f'<hp:equation version="{version}">\n'
        f'  <hp:script>{escaped}</hp:script>\n'
        f'</hp:equation>'
    )
