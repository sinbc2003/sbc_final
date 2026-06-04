import {
  FileText, Brain, FileOutput, Table, Wand2, Settings, Box,
  FileSpreadsheet, Presentation, ScanText, Globe, Scissors,
  Image, Merge, Sparkles, Tag, Languages, Upload, Type,
  LayoutTemplate, PenTool, Database,
} from "lucide-react";

/** 노드 아이콘 ID → lucide 컴포넌트 매핑 (공유) */
export const ICON_MAP: Record<string, any> = {
  "file-text": FileText,
  brain: Brain,
  "file-output": FileOutput,
  table: Table,
  wand: Wand2,
  settings: Settings,
  box: Box,
  "file-spreadsheet": FileSpreadsheet,
  presentation: Presentation,
  scan: ScanText,
  globe: Globe,
  scissors: Scissors,
  image: Image,
  merge: Merge,
  sparkles: Sparkles,
  tag: Tag,
  languages: Languages,
  upload: Upload,
  type: Type,
  layout: LayoutTemplate,
  "pen-tool": PenTool,
  database: Database,
};
