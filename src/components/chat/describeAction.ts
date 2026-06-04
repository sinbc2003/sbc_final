/** 액션을 사용자 친화적 텍스트로 변환. */
export function describeAction(act: { action: string; params: any }): string {
  const p = act.params || {};
  switch (act.action) {
    case "set_cell": return `셀 ${p.cell} = "${p.value}"`;
    case "set_cells": return `${Object.keys(p.cells || {}).length}개 셀 설정`;
    case "replace_text": case "find_and_replace_all": return `"${p.find || p.old_text || ""}" → "${p.replace || p.new_text || ""}"`;
    case "insert_text": return `텍스트 삽입: "${(p.text || "").slice(0, 40)}"`;
    case "set_paragraph": return `문단 ${p.paragraph} 수정`;
    case "append_paragraph": return `문단 추가: "${(p.text || "").slice(0, 40)}"`;
    case "format_paragraph": return `문단 ${p.paragraph} 서식`;
    case "set_text": return `슬라이드 ${p.slide} 텍스트 수정`;
    case "add_slide": return `슬라이드 추가${p.title ? `: ${p.title}` : ""}`;
    case "delete_slide": return `슬라이드 ${p.slide} 삭제`;
    case "replace_cell_content": return `셀 [${p.block_id}] → "${(p.new_text || "").slice(0, 30)}"`;
    case "replace_paragraph": return `문단 [${p.block_id}] → "${(p.new_text || "").slice(0, 30)}"`;
    case "apply_para_style": return `[${p.block_id}] 서식 변경`;
    case "replace_table_row": return `[${p.block_id}] 행 교체`;
    case "set_table_cell": return `표${p.table || 1}[${p.row},${p.col}] = "${p.text}"`;
    case "active_sheet": return `시트 전환: ${p.sheet}`;
    case "add_sheet": return `시트 추가: ${p.name}`;
    case "insert_row": return `${p.row}행 삽입`;
    case "delete_row": return `${p.row}행 삭제`;
    case "auto_fit": return "열 너비 자동 조정";
    case "save": return "저장";
    case "create_table": return `${p.rows}x${p.cols} 표 생성`;
    case "style_cell": return `[${p.block_id}] 셀 서식${p.bg_color ? ` 배경${p.bg_color}` : ""}`;
    case "style_row": return `[${p.block_id}] 행 서식${p.bg_color ? ` 배경${p.bg_color}` : ""}`;
    case "merge_cells": return `[${p.block_id}] 셀 병합 (→${p.right || 0}, ↓${p.down || 0})`;
    case "set_table_col_width": return `열 너비 설정`;
    case "format_range": return `${p.range} 서식${p.bg_color ? ` 배경${p.bg_color}` : ""}`;
    case "set_col_width": return `열 ${p.col} 너비 = ${p.width}`;
    case "set_row_height": return `${p.row}행 높이 = ${p.height}`;
    case "merge_range": return `${p.range} 병합`;
    case "border": return `${p.range} 테두리`;
    case "set_formula": return `${p.cell} 수식`;
    case "format_text": return `슬라이드 ${p.slide} 텍스트 서식`;
    case "set_slide_bg": return `슬라이드 ${p.slide} 배경색`;
    case "add_shape": return `슬라이드 ${p.slide} 도형 추가`;
    case "style_table_row": return `표${p.table} ${p.row}행 서식${p.bg_color ? ` 배경${p.bg_color}` : ""}`;
    case "style_table_cell": return `표${p.table} [${p.row},${p.col}] 셀 서식`;
    case "set_table_widths": return `표${p.table} 열 너비 설정`;
    case "format_text": return `텍스트 서식${p.font_size ? ` ${p.font_size}pt` : ""}${p.bold ? " 볼드" : ""}`;
    default: return `${act.action}: ${JSON.stringify(p).slice(0, 50)}`;
  }
}
