"""승인 UX 피드백 수집 — 후속 모델 학습·시스템 개선용 (§36).

사용자가 검토 패널에서 내린 결정(승인/거절/값 수정)을 로컬 JSONL로 축적한다.
- 저장 위치: DATA_DIR/feedback/approval_feedback.jsonl (로컬 전용, 외부 전송 없음)
- 신호 등급: edited(값 수정) = 정답 라벨 > rejected = 오답 신호 > approved = 정답 추정
- 학습 활용: (grid+지시 → 수정본) SFT 쌍 / rejected는 필터·DPO 네거티브
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from engine.paths import DATA_DIR

router = APIRouter()

FEEDBACK_DIR = DATA_DIR / "feedback"


class ApprovalItem(BaseModel):
    id: str = ""                 # 셀ID(fill) 또는 액션명(actions)
    label: str = ""
    proposed: Any = None         # 모델 제안값(fill: 값, actions: params)
    decision: str = "approved"   # approved | rejected | edited
    final_value: Any = None      # edited일 때 사용자가 고친 값


class ApprovalFeedback(BaseModel):
    kind: str                    # "fill" | "actions"
    outcome: str                 # "applied" | "cancelled"
    items: list[ApprovalItem] = []
    instruction: str = ""        # 사용자의 원 지시
    file: str = ""               # 대상 문서 (파일명만 저장)
    model: str = ""
    app_type: str = ""


def record_feedback(fb: dict) -> str:
    """피드백 1건을 JSONL로 추가. 반환: 저장 경로."""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    path = FEEDBACK_DIR / "approval_feedback.jsonl"
    fb = dict(fb)
    fb["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    # 경로 전체는 저장하지 않는다 — 파일명만 (로컬이지만 습관적으로 최소화)
    if fb.get("file"):
        fb["file"] = str(fb["file"]).replace("\\", "/").rsplit("/", 1)[-1]
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(fb, ensure_ascii=False) + "\n")
    return str(path)


@router.post("/api/feedback/approval")
async def feedback_approval(req: ApprovalFeedback):
    path = record_feedback(req.model_dump())
    return {"ok": True, "path": path}


@router.get("/api/feedback/stats")
async def feedback_stats():
    """축적 현황 — 결정 종류별 카운트 (학습 재료가 얼마나 쌓였는지)."""
    path = FEEDBACK_DIR / "approval_feedback.jsonl"
    counts = {"events": 0, "approved": 0, "rejected": 0, "edited": 0}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                counts["events"] += 1
                for it in d.get("items", []):
                    dec = it.get("decision", "")
                    if dec in counts:
                        counts[dec] += 1
    return counts
