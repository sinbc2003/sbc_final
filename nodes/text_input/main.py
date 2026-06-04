"""
텍스트 입력 노드.

파라미터로 받은 텍스트를 그대로 출력한다.
"""


def execute(inputs: dict, params: dict, context: dict) -> dict:
    content = params.get("content", "")

    context["progress"](1.0)
    context["log"](f"텍스트 입력 ({len(content)} 글자)")

    return {"텍스트": content}
