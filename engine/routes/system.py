"""시스템, 노드, 모델, 디자인스킬 엔드포인트."""

from fastapi import APIRouter
from engine import deps
from engine.memory_manager import get_memory_profile, get_system_info

router = APIRouter()


@router.get("/api/nodes")
async def list_nodes():
    result = []
    for nd in deps.registry.list_nodes():
        result.append({
            "id": nd.id, "name": nd.name, "version": nd.version,
            "category": nd.category, "icon": nd.icon, "author": nd.author,
            "description": nd.description,
            "inputs": [{"name": p.name, "type": p.type, "accept": p.accept, "description": p.description} for p in nd.inputs],
            "outputs": [{"name": p.name, "type": p.type, "accept": p.accept, "description": p.description} for p in nd.outputs],
            "params": nd.params, "resource": nd.resource, "use_when": nd.use_when,
        })
    return result


@router.get("/api/system")
async def system_info():
    info = get_system_info()
    profile = get_memory_profile()
    return {**info, "recommended_quant": profile.recommended_quant,
            "recommended_ctx": profile.recommended_ctx,
            "model_budget_mb": profile.model_budget_mb,
            "available_ram_gb": profile.available_gb}


@router.get("/api/health")
async def health():
    return {"status": "ok", "nodes": len(deps.registry), **deps.store.get_stats()}


@router.get("/api/models")
async def list_models():
    if deps.llm_manager:
        return deps.llm_manager.list_available_models()
    return []


@router.get("/api/design-skills")
async def list_design_skills():
    skills_dir = deps.ROOT / "engine" / "skills" / "design"
    result = []
    labels = {
        "default": "기본", "official": "공문서", "modern": "모던 클린",
        "colorful": "컬러풀", "education": "교육자료", "business": "비즈니스",
    }
    if skills_dir.exists():
        for f in sorted(skills_dir.glob("*.md")):
            sid = f.stem
            result.append({"id": sid, "name": labels.get(sid, sid)})
    return result
