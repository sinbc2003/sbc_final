"""
grid_live — hwpx_grid 배치 결정을 한/글 COM으로 라이브 기록.

핵심 아이디어 (§16-3 "스캔·그리드 매칭"):
  - 파일-그리드(hwpx_grid)는 병합 인지 + (행,열) 좌표가 명확 → gemma의 배치
    결정은 검증된 그리드 셀ID(enum 강제)로 받는다.
  - COM InitScan은 셀을 문서 읽기순 일렬로만 주지만, HWPX의 tc(XML) 순서와
    같은 문서 내부 순서다 → 두 목록을 인덱스로 정렬하고 **셀 텍스트 검산**으로
    확정한다. 검산에 실패한 셀은 기록하지 않는다(오기록 방지, fail-safe).
  - 기록은 Inline AI와 같은 set_pos → is_cell → SelectAll → insert_text —
    사용자 눈앞에서 캐럿이 움직이며 채워진다.

역할 분담(설계 원칙 그대로): gemma = 의미 매칭(어느 셀ID에 무엇),
정렬·좌표·검산·기록 = 전부 결정적 코드.
"""
from __future__ import annotations

import os
import time
from pathlib import Path


def _norm(s: str) -> str:
    """검산용 정규화 — 공백 전부 제거.

    멀티 문단 셀을 그리드(_elem_text)는 무공백, 스캔은 공백으로 연결하므로
    공백 차이는 무시하고 내용만 비교한다 (벤치 실측: 1126셀 중 68셀이 이 차이).
    """
    return "".join((s or "").split())


def grid_cells_in_doc_order(doc) -> list[tuple]:
    """그리드 셀을 XML(tr/tc) 문서 순서로 — [(셀ID, 정규화 텍스트)].

    HWPX의 tc는 tr별 colAddr 오름차순으로 나타나므로 (row, col) 정렬 = XML 순서.
    중첩 표는 스캔 순서(부모 셀 내부에 끼어듦)와 어긋나므로 라이브 매핑 미지원.
    """
    cells: list[tuple] = []
    for grid in doc.tables:
        if "(중첩 표)" in (grid.context or ""):
            raise ValueError("중첩 표 문서는 라이브 매핑 미지원 — 파일 채움을 사용하세요")
        for (r, c), cell in sorted(grid.cells.items()):
            cells.append((f"{grid.key}_r{r}_c{c}", _norm(cell.text)))
    return cells


def scan_cells_in_order(elements: list[dict]) -> list[tuple]:
    """InitScan 결과의 표 셀을 최초 등장 순서로 — [(list_id, 텍스트, pos)].

    한 셀(list_id)이 여러 스캔 요소(문단)로 나뉘어도 하나로 합친다.
    pos = 그 셀의 첫 요소 위치 (fill_hwp_by_cells와 같은 좌표 사용법).
    """
    seen: dict = {}
    order: list = []
    for e in elements:
        if e.get("type") != "td":
            continue
        lid = e.get("list_id")
        if lid not in seen:
            seen[lid] = {"texts": [], "pos": e["pos"]}
            order.append(lid)
        t = (e.get("text") or "").strip()
        if t:
            seen[lid]["texts"].append(t)
    return [(lid, _norm(" ".join(seen[lid]["texts"])), seen[lid]["pos"])
            for lid in order]


def align_grid_to_scan(doc, elements: list[dict], log=None) -> tuple:
    """그리드 셀ID ↔ COM 스캔 좌표 매핑. 텍스트 검산 통과 셀만 반환.

    반환: (mapping {셀ID: [list_id, para, char]}, stats)
    셀 수가 다르면 순서 가설이 깨진 것 → 빈 매핑(라이브 중단, 파일 폴백 권장).
    """
    def _log(msg):
        if log:
            log(msg)

    gcells = grid_cells_in_doc_order(doc)
    scells = scan_cells_in_order(elements)
    stats = {"grid_cells": len(gcells), "scan_cells": len(scells),
             "matched": 0, "mismatched": 0}

    if len(gcells) != len(scells):
        _log(f"셀 수 불일치: 그리드 {len(gcells)} vs 스캔 {len(scells)} — 라이브 매핑 중단")
        return {}, stats

    mapping: dict = {}
    for (cid, gtext), (lid, stext, pos) in zip(gcells, scells):
        if gtext == stext:
            mapping[cid] = pos
            stats["matched"] += 1
        else:
            stats["mismatched"] += 1
            if stats["mismatched"] <= 5:
                _log(f"  검산 불일치 {cid}: 그리드='{gtext[:24]}' vs 스캔='{stext[:24]}'")
    if stats["mismatched"]:
        _log(f"검산: {stats['matched']}/{len(gcells)} 일치, {stats['mismatched']} 불일치(기록 제외)")
    # 대량 불일치 = 순서 가설 붕괴 또는 화면·파일 불일치(미저장 수정) 의심 →
    # 부분 기록도 위험하므로 전체 중단.
    if gcells and stats["mismatched"] > max(2, len(gcells) * 0.2):
        _log("불일치 과다 — 화면 문서와 파일이 다르거나 순서가 어긋남. 라이브 기록 중단")
        return {}, stats
    return mapping, stats


def fill_grid_live(form_path: str, fill_data: dict, elements: list[dict],
                   log=None, output_dir: str = "") -> dict:
    """gemma의 {셀ID|누름틀명: 값}을 열린 한/글 문서에 라이브 기록. (COM 스레드 전용)

    - 셀ID(s_t_r_c): 그리드↔스캔 정렬 좌표로 set_pos → SelectAll → insert_text
    - 누름틀명: put_field_text (네이티브, 정확 이름 일치)
    - 본문 블랭크ID(s_u): 라이브 미지원 → 건너뛰고 보고
    완료 후 '_완성' 사본으로 저장. 반환: {output, filled, skipped, stats}
    """
    def _log(msg):
        if log:
            log(msg)

    import pythoncom
    pythoncom.CoInitialize()

    from engine.hwpml.hwpx_grid import ID_RE, BODY_ID_RE, parse_hwpx
    from engine.form_assist import _connect_hwp

    hwp, _ = _connect_hwp(form_path, _log)

    grid_map = {k: v for k, v in fill_data.items() if ID_RE.match(str(k))}
    body_map = {k: v for k, v in fill_data.items() if BODY_ID_RE.match(str(k))}
    field_map = {k: v for k, v in fill_data.items()
                 if not ID_RE.match(str(k)) and not BODY_ID_RE.match(str(k))}

    skipped: list = []
    filled = 0
    stats: dict = {}

    # ── 그리드 셀 → 정렬 좌표로 라이브 기록 ──
    if grid_map:
        from engine.hwpml.hwpx_grid import relocate_below_markers
        doc = parse_hwpx(form_path)
        # '이하빈칸' 마커를 채워진 마지막 행 아래로 이동 (파일 경로와 동일 규칙)
        try:
            extra = relocate_below_markers(doc, grid_map, log=_log)
            grid_map = {**extra, **grid_map}
        except Exception as e:
            _log(f"마커 이동 건너뜀: {e}")
        try:
            mapping, stats = align_grid_to_scan(doc, elements, log=_log)
        except ValueError as e:
            _log(str(e))
            mapping, stats = {}, {"error": str(e)}
        # 기록 직전 재검증용 스냅샷 텍스트 (스캔↔기록 사이 사용자 편집 방어)
        expected = {f"{g.key}_r{r}_c{c}": _norm(cell.text)
                    for g in doc.tables for (r, c), cell in g.cells.items()}
        for cid, value in grid_map.items():
            val = str(value).strip()
            clear = not val  # 마커 이동의 원위치 클리어("")
            pos = mapping.get(cid)
            if not pos:
                skipped.append(cid)
                continue
            try:
                # set_pos 실패 시 캐럿이 직전 위치(방금 채운 셀)에 남는다 —
                # 그대로 진행하면 이전 셀을 덮어쓰므로 반드시 반환값 확인.
                if not hwp.set_pos(*pos):
                    skipped.append(cid)
                    _log(f"  셀 {cid}: set_pos 실패 — 건너뜀")
                    continue
                if not hwp.is_cell():
                    skipped.append(cid)
                    _log(f"  셀 {cid}: is_cell 아님 — 건너뜀")
                    continue
                hwp.SelectAll()
                # 기록 직전 셀 내용 재검증 — 스캔 시점과 다르면(사용자 편집 등)
                # 오기록 위험이므로 건너뜀 (TOCTOU 방어)
                cur = _norm(hwp.get_selected_text(keep_select=True) or "")
                if cur != expected.get(cid, ""):
                    hwp.Cancel()
                    skipped.append(cid)
                    _log(f"  셀 {cid}: 내용 변경 감지('{cur[:16]}') — 건너뜀")
                    continue
                if clear:
                    hwp.Delete()
                else:
                    hwp.insert_text(val)
                filled += 1
                if not clear:
                    _log(f"  셀 {cid} → {val[:40]}")
                time.sleep(0.03)
            except Exception as e:
                skipped.append(cid)
                _log(f"  셀 {cid} 실패: {e}")

    # ── 누름틀 → put_field_text (네이티브 정확 매칭) ──
    # put_field_text는 없는 필드를 무시(무예외)하므로 존재 확인 후 채움.
    for name, value in field_map.items():
        val = str(value).strip()
        if not val:
            continue
        try:
            if not hwp.field_exist(str(name)):
                skipped.append(str(name))
                _log(f"  누름틀 {name}: 문서에 없음 — 건너뜀")
                continue
            hwp.put_field_text(str(name), val)
            filled += 1
            _log(f"  누름틀 {name} → {val[:40]}")
        except Exception as e:
            skipped.append(str(name))
            _log(f"  누름틀 {name} 실패: {e}")

    # ── 본문 블랭크 → find 순회로 라이브 교체 ──
    # 문서 순서의 밑줄런 목록(장식 포함, XML)과 COM find(Forward)가 같은
    # 순서로 만난다는 원리(셀 정렬과 동일). 표 안 히트는 is_cell로 스킵하고,
    # 비대상 본문 런은 동일 문자열 재삽입으로 통과(캐럿 전진, 내용 불변).
    if body_map:
        from engine.hwpml.hwpx_grid import body_blank_runs
        runs = body_blank_runs(form_path)
        targets = {bid for bid in body_map}
        try:
            hwp.MoveDocBegin()
            for bid, run_str in runs:
                # 이 런을 문서에서 찾기 — 표 안 동일 문자열은 스킵
                found_body = False
                for _guard in range(50):
                    if not hwp.find(run_str, "Forward"):
                        break
                    if hwp.is_cell():
                        # 표 안 히트: 동일 문자열 재삽입으로 캐럿만 전진
                        hwp.insert_text(run_str)
                        continue
                    found_body = True
                    break
                if not found_body:
                    # 문서에서 못 찾음(사용자 편집 등) — 순서 신뢰 불가, 잔여 중단
                    _log(f"본문 밑줄 '{run_str[:8]}…' 미발견 — 잔여 본문 블랭크 중단")
                    for b in targets:
                        if str(body_map.get(b, "")).strip():
                            skipped.append(b)
                    break
                if bid in targets:
                    val = str(body_map[bid]).strip()
                    if val:
                        hwp.insert_text(val)  # find가 선택한 런을 값으로 교체
                        filled += 1
                        _log(f"  본문 {bid} → {val[:40]}")
                    else:
                        hwp.insert_text(run_str)  # 빈 값 → 밑줄 보존
                    targets.discard(bid)
                else:
                    hwp.insert_text(run_str)  # 비대상 → 통과
                if not targets:
                    break
        except Exception as e:
            _log(f"본문 블랭크 라이브 기록 실패: {e}")
            for b in targets:
                skipped.append(b)

    _log(f"라이브 기록: {filled}개 완료" + (f", {len(skipped)}개 건너뜀" if skipped else ""))

    # ── '_완성' 사본 저장 ──
    output_path = ""
    if filled:
        save_dir = output_dir
        if not save_dir:
            desktop = Path.home() / "Desktop"
            save_dir = str(desktop) if desktop.exists() else os.path.dirname(form_path)
        output_path = os.path.join(
            save_dir, Path(form_path).stem + "_완성" + Path(form_path).suffix)
        try:
            try:
                hwp.set_message_box_mode(0x00011011)  # 덮어쓰기 등 대화상자 자동 확인
            except Exception:
                pass
            hwp.SaveAs(os.path.abspath(output_path))
            if os.path.exists(output_path):
                _log(f"저장: {output_path}")
            else:
                _log(f"저장 실패: 파일이 생성되지 않음 — {output_path}")
                output_path = ""
        except Exception as e:
            _log(f"저장 실패: {e}")
            output_path = ""

    # ── 저장본 재추출 검증 (정직한 보고 — 라이브는 재시도 대신 미반영 보고) ──
    verified, missing = 0, []
    if output_path:
        try:
            from engine.form_assist import _verify_hwpx_fill
            ver, mis = _verify_hwpx_fill(output_path, fill_data)
            verified, missing = len(ver), list(mis)
            if missing:
                _log(f"검증: {verified}/{len([v for v in fill_data.values() if str(v).strip()])} "
                     f"반영, 미반영 {len(missing)}개: {missing[:5]}")
        except Exception as e:
            _log(f"검증 건너뜀: {e}")

    return {"output": output_path, "filled": filled, "skipped": skipped,
            "stats": stats, "verified": verified, "missing": missing}
