#!/usr/bin/env python3
"""
TeacherFlow CLI 파이프라인 러너.

사용법:
  python run_pipeline.py workflow.json
  python run_pipeline.py workflow.json --input n1:파일=test.pdf
  python run_pipeline.py --list-nodes
  python run_pipeline.py --info pdf_to_md

옵션:
  --input NODE_ID:PORT=VALUE    시작 노드에 입력값 주입 (여러 번 사용 가능)
  --list-nodes                  등록된 노드 목록 출력
  --info NODE_ID                노드 상세 정보 출력
  --nodes-dir PATH              노드 폴더 경로 (기본: ./nodes)
  --models-dir PATH             모델 폴더 경로 (기본: ./models)
  --config KEY=VALUE            설정값 (여러 번 사용 가능, 예: claude_api_key=sk-...)
  --output-dir PATH             최종 출력 파일 복사 경로
  --verbose                     상세 로그
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.loader import NodeRegistry
from engine.runner import PipelineRunner, Workflow
from engine.llm_manager import LLMManager
from engine.memory_manager import get_memory_profile, get_system_info


def parse_input_arg(arg: str) -> tuple[str, str, str]:
    """'n1:파일=test.pdf' → ('n1', '파일', 'test.pdf')"""
    node_part, _, value = arg.partition("=")
    node_id, _, port = node_part.partition(":")
    if not node_id or not port or not value:
        raise ValueError(f"잘못된 입력 형식: {arg!r} (올바른 형식: NODE_ID:PORT=VALUE)")
    return node_id, port, value


def print_node_list(registry: NodeRegistry):
    """등록된 노드 목록 출력."""
    nodes = registry.list_nodes()
    if not nodes:
        print("등록된 노드 없음")
        return

    print(f"\n등록된 노드 ({len(nodes)}개):")
    print("-" * 60)
    for nd in sorted(nodes, key=lambda n: n.category):
        inputs = ", ".join(f"{p.name}({p.type})" for p in nd.inputs)
        outputs = ", ".join(f"{p.name}({p.type})" for p in nd.outputs)
        print(f"  [{nd.category}] {nd.id}")
        print(f"    {nd.name}")
        print(f"    입력: {inputs or '없음'}")
        print(f"    출력: {outputs or '없음'}")
        print()


def print_node_info(registry: NodeRegistry, node_id: str):
    """노드 상세 정보 출력."""
    nd = registry.get(node_id)
    if not nd:
        print(f"노드 '{node_id}'를 찾을 수 없습니다")
        return

    print(f"\n{'=' * 60}")
    print(f"  {nd.name} (v{nd.version})")
    print(f"  ID: {nd.id}")
    print(f"  카테고리: {nd.category}")
    print(f"  작성자: {nd.author}")
    print(f"{'=' * 60}")
    print(f"\n설명:\n  {nd.description}")

    if nd.inputs:
        print("\n입력 포트:")
        for p in nd.inputs:
            accept = f" [{', '.join(p.accept)}]" if p.accept else ""
            print(f"  - {p.name} ({p.type}{accept}): {p.description}")

    if nd.outputs:
        print("\n출력 포트:")
        for p in nd.outputs:
            accept = f" [{', '.join(p.accept)}]" if p.accept else ""
            print(f"  - {p.name} ({p.type}{accept}): {p.description}")

    if nd.params:
        print("\n파라미터:")
        for param in nd.params:
            default = param.get("default", "")
            print(f"  - {param['id']} ({param.get('type', '?')}): "
                  f"{param.get('description', '')} [기본: {default}]")

    if nd.use_when:
        print("\n사용 시점:")
        for uw in nd.use_when:
            print(f"  - {uw}")


def main():
    parser = argparse.ArgumentParser(
        description="TeacherFlow 파이프라인 러너",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("workflow", nargs="?", help="워크플로우 JSON 파일 경로")
    parser.add_argument("--input", action="append", default=[],
                        help="시작 노드 입력값 (NODE_ID:PORT=VALUE)")
    parser.add_argument("--list-nodes", action="store_true",
                        help="등록된 노드 목록")
    parser.add_argument("--info", help="노드 상세 정보")
    parser.add_argument("--nodes-dir", default="./nodes",
                        help="노드 폴더 경로")
    parser.add_argument("--models-dir", default="./models",
                        help="모델 폴더 경로")
    parser.add_argument("--config", action="append", default=[],
                        help="설정값 (KEY=VALUE)")
    parser.add_argument("--output-dir", help="최종 출력 파일 복사 경로")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="상세 로그")
    parser.add_argument("--system-info", action="store_true",
                        help="시스템 정보 출력")

    args = parser.parse_args()
    nodes_dir = Path(args.nodes_dir).resolve()
    models_dir = Path(args.models_dir).resolve()

    # 시스템 정보
    if args.system_info:
        info = get_system_info()
        profile = get_memory_profile()
        print("\n시스템 정보:")
        for k, v in info.items():
            print(f"  {k}: {v}")
        print(f"\nLLM 권장 설정:")
        print(f"  양자화: {profile.recommended_quant}")
        print(f"  컨텍스트: {profile.recommended_ctx}")
        print(f"  모델 예산: {profile.model_budget_mb}MB")
        return

    # 노드 로드
    registry = NodeRegistry()
    loaded = registry.load_all(nodes_dir)
    if args.verbose:
        print(f"노드 {len(loaded)}개 로드: {', '.join(loaded)}")

    # 노드 목록
    if args.list_nodes:
        print_node_list(registry)
        return

    # 노드 정보
    if args.info:
        print_node_info(registry, args.info)
        return

    # 워크플로우 실행
    if not args.workflow:
        parser.print_help()
        sys.exit(1)

    workflow_path = Path(args.workflow).resolve()
    if not workflow_path.exists():
        print(f"워크플로우 파일 없음: {workflow_path}")
        sys.exit(1)

    # 설정
    config = {}
    for c in args.config:
        key, _, value = c.partition("=")
        config[key] = value

    # 초기 입력
    initial_inputs: dict[str, dict] = {}
    for inp in args.input:
        node_id, port, value = parse_input_arg(inp)
        if node_id not in initial_inputs:
            initial_inputs[node_id] = {}
        initial_inputs[node_id][port] = value

    # 워크플로우 로드
    workflow = Workflow.from_file(workflow_path)
    print(f"\n워크플로우: {workflow.name}")
    print(f"설명: {workflow.description}")
    print(f"노드 {len(workflow.nodes)}개, 연결 {len(workflow.edges)}개")
    print("-" * 60)

    # LLM 관리자
    llm = LLMManager(models_dir=models_dir, config=config)

    # 실행
    def on_progress(node_id, value):
        if args.verbose:
            bar = "█" * int(value * 20) + "░" * (20 - int(value * 20))
            print(f"  [{node_id}] |{bar}| {value:.0%}")

    def on_log(node_id, message):
        print(f"  [{node_id}] {message}")

    runner = PipelineRunner(
        registry=registry,
        llm_manager=llm,
        config=config,
        on_progress=on_progress if args.verbose else None,
        on_log=on_log,
    )

    result = runner.run(workflow, initial_inputs)

    # 결과 출력
    print("-" * 60)
    if result.success:
        print(f"\n✓ 파이프라인 완료 ({result.elapsed_seconds:.1f}초)")
    else:
        print(f"\n✗ 파이프라인 실패 ({result.elapsed_seconds:.1f}초)")
        for err in result.errors:
            print(f"  ERROR: {err}")

    # 노드별 타이밍
    if result.node_timings:
        print("\n노드별 실행 시간:")
        for nid, t in result.node_timings.items():
            print(f"  {nid}: {t:.1f}초")

    # 최종 출력
    if result.outputs:
        print("\n출력 데이터:")
        for nid, outputs in result.outputs.items():
            for port, value in outputs.items():
                display = str(value)
                if len(display) > 200:
                    display = display[:200] + "..."
                print(f"  {nid}.{port} = {display}")

                # 파일이면 output-dir로 복사
                if args.output_dir and isinstance(value, str) and Path(value).exists():
                    out_dir = Path(args.output_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    dest = out_dir / Path(value).name
                    shutil.copy2(value, dest)
                    print(f"    → 복사됨: {dest}")

    # LLM 정리
    llm.cleanup()


if __name__ == "__main__":
    main()
