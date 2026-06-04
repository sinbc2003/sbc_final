"""
텍스트 템플릿 노드.

템플릿의 {{변수명}} 패턴을 inputs 값으로 치환한다.
"""

import re


def execute(inputs: dict, params: dict, context: dict) -> dict:
    template = params.get("template", "{{입력1}}\n\n---\n\n{{입력2}}")

    context["progress"](0.1)
    context["log"]("템플릿 치환 시작")

    # {{변수명}} 패턴 치환
    def replacer(match):
        key = match.group(1).strip()
        if key in inputs:
            return str(inputs[key])
        # params에서도 검색
        if key in params:
            return str(params[key])
        return match.group(0)  # 매칭되지 않으면 원본 유지

    result = re.sub(r"\{\{(.+?)\}\}", replacer, template)

    context["progress"](1.0)
    context["log"](f"치환 완료 ({len(result)} 글자)")

    return {"텍스트": result}
