"""
노드 마켓플레이스 — 원격 노드 레지스트리 + 다운로드/설치/검증.

구조:
  - 원격 레지스트리 (JSON API): 노드 메타데이터 목록
  - 노드 패키지: node.yaml + main.py + (선택) requirements.txt
  - 설치: nodes/ 폴더에 자동 배치
  - 버전 관리: node.yaml의 version 필드 기준
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import yaml


class NodeMarketplace:
    """노드 마켓플레이스 클라이언트."""

    def __init__(self, nodes_dir: Path, data_dir: Path, registry_url: str = ""):
        self._nodes_dir = nodes_dir
        self._cache_dir = data_dir / "marketplace_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._registry_url = registry_url
        self._installed_index = data_dir / "installed_nodes.json"
        self._installed: dict[str, dict] = self._load_installed()

    def _load_installed(self) -> dict[str, dict]:
        if self._installed_index.exists():
            try:
                return json.loads(self._installed_index.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_installed(self):
        self._installed_index.write_text(
            json.dumps(self._installed, ensure_ascii=False, indent=2), "utf-8"
        )

    # ── 로컬 노드 스캔 ──────────────────────────────

    def scan_local(self) -> list[dict[str, Any]]:
        """로컬 설치된 노드 목록 (node.yaml 파싱)."""
        result = []
        for d in sorted(self._nodes_dir.iterdir()):
            yaml_path = d / "node.yaml"
            if not yaml_path.exists():
                continue
            try:
                meta = yaml.safe_load(yaml_path.read_text("utf-8"))
                meta["_local_path"] = str(d)
                meta["_installed"] = True
                result.append(meta)
            except Exception:
                continue
        return result

    # ── 원격 레지스트리 ──────────────────────────────

    def fetch_registry(self) -> list[dict[str, Any]]:
        """원격 노드 목록 가져오기."""
        if not self._registry_url:
            return []
        try:
            import requests
            resp = requests.get(f"{self._registry_url}/nodes", timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    def check_updates(self) -> dict[str, Any]:
        """업데이트 가능한 노드 확인."""
        local = {n["id"]: n.get("version", "0.0.0") for n in self.scan_local()}
        remote = self.fetch_registry()

        updates = []
        new_nodes = []
        for rn in remote:
            rid = rn.get("id", "")
            rver = rn.get("version", "0.0.0")
            if rid in local:
                if _version_gt(rver, local[rid]):
                    updates.append({"id": rid, "name": rn.get("name", rid),
                                    "current": local[rid], "available": rver})
            else:
                new_nodes.append({"id": rid, "name": rn.get("name", rid),
                                  "version": rver, "category": rn.get("category", "")})

        return {
            "available": len(updates) + len(new_nodes),
            "updates": updates,
            "new_nodes": new_nodes,
            "nodes": [u["name"] for u in updates] + [n["name"] for n in new_nodes],
        }

    # ── 설치 / 업데이트 ─────────────────────────────

    def install_node(self, node_id: str) -> dict[str, Any]:
        """노드 다운로드 + 설치."""
        if not self._registry_url:
            return {"success": False, "error": "마켓플레이스 URL 미설정"}

        try:
            import requests
            # 노드 패키지 다운로드 (ZIP)
            resp = requests.get(
                f"{self._registry_url}/nodes/{node_id}/download",
                timeout=30,
            )
            if resp.status_code != 200:
                return {"success": False, "error": f"다운로드 실패: {resp.status_code}"}

            # ZIP 검증 + 설치
            return self._install_from_zip(node_id, resp.content)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def install_from_file(self, zip_path: Path) -> dict[str, Any]:
        """로컬 ZIP 파일에서 노드 설치."""
        data = zip_path.read_bytes()
        # ZIP 내 node.yaml에서 ID 추출
        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                for name in zf.namelist():
                    if name.endswith("node.yaml"):
                        meta = yaml.safe_load(zf.read(name))
                        node_id = meta.get("id", "")
                        if node_id:
                            return self._install_from_zip(node_id, data)
        except Exception as e:
            return {"success": False, "error": f"ZIP 파싱 오류: {e}"}
        return {"success": False, "error": "node.yaml을 찾을 수 없음"}

    def _install_from_zip(self, node_id: str, zip_data: bytes) -> dict[str, Any]:
        """ZIP 데이터에서 노드 설치."""
        target_dir = self._nodes_dir / node_id

        # 기존 노드 백업
        backup_dir = None
        if target_dir.exists():
            backup_dir = self._cache_dir / f"{node_id}_backup"
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(target_dir, backup_dir)

        try:
            # 압축 해제
            target_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(BytesIO(zip_data)) as zf:
                # 보안: 경로 탈출 방지
                for info in zf.infolist():
                    if info.filename.startswith("/") or ".." in info.filename:
                        raise ValueError(f"위험한 경로: {info.filename}")
                zf.extractall(target_dir)

            # node.yaml 검증
            yaml_path = target_dir / "node.yaml"
            if not yaml_path.exists():
                # 하위 디렉토리에 있을 수 있음
                for p in target_dir.rglob("node.yaml"):
                    yaml_path = p
                    break

            if not yaml_path.exists():
                raise FileNotFoundError("node.yaml 없음")

            meta = yaml.safe_load(yaml_path.read_text("utf-8"))

            # main.py 검증
            main_path = yaml_path.parent / "main.py"
            if not main_path.exists():
                raise FileNotFoundError("main.py 없음")

            # 설치 기록
            self._installed[node_id] = {
                "version": meta.get("version", "0.0.0"),
                "name": meta.get("name", node_id),
                "checksum": hashlib.sha256(zip_data).hexdigest(),
            }
            self._save_installed()

            # 백업 제거
            if backup_dir and backup_dir.exists():
                shutil.rmtree(backup_dir)

            return {"success": True, "id": node_id, "name": meta.get("name", node_id),
                    "version": meta.get("version", "0.0.0")}

        except Exception as e:
            # 실패 시 백업 복원
            if backup_dir and backup_dir.exists():
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(backup_dir, target_dir)
                shutil.rmtree(backup_dir)
            return {"success": False, "error": str(e)}

    def uninstall_node(self, node_id: str) -> dict[str, Any]:
        """노드 제거."""
        target_dir = self._nodes_dir / node_id
        if not target_dir.exists():
            return {"success": False, "error": "노드 없음"}

        shutil.rmtree(target_dir)
        self._installed.pop(node_id, None)
        self._save_installed()
        return {"success": True, "id": node_id}


def _version_gt(a: str, b: str) -> bool:
    """a > b 버전 비교."""
    try:
        a_parts = [int(x) for x in a.split(".")]
        b_parts = [int(x) for x in b.split(".")]
        return a_parts > b_parts
    except (ValueError, AttributeError):
        return a > b
