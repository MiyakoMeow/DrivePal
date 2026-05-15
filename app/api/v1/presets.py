"""v1 presets 路由."""

from fastapi import APIRouter, Request

from app.api.errors import safe_memory_call
from app.api.schemas import SavePresetRequest, ScenarioPresetResponse
from app.config import user_data_dir
from app.schemas.context import DrivingContext, ScenarioPreset
from app.storage.toml_store import TOMLStore

router = APIRouter()


def _preset_store(user_id: str) -> TOMLStore:
    """获取场景预设存储实例."""
    return TOMLStore(
        user_dir=user_data_dir(user_id),
        filename="scenario_presets.toml",
        default_factory=list,
    )


def _restore_toml_nones(ctx_raw: dict) -> dict:
    """TOML 不支持 None，_clean_for_toml 将 None 序列化为空字符串，此处还原."""
    safe = {k: v for k, v in ctx_raw.items() if k in DrivingContext.model_fields}
    sp = safe.get("spatial", {})
    if isinstance(sp, dict):
        for key in ("destination", "eta_minutes", "heading"):
            if sp.get(key) == "":
                sp[key] = None
    return safe


def _dict_to_preset_response(p: dict) -> ScenarioPresetResponse:
    """存储 dict → ScenarioPresetResponse."""
    ctx_raw = p.get("context", {})
    safe = _restore_toml_nones(ctx_raw)
    ctx = DrivingContext.model_validate(safe)
    return ScenarioPresetResponse(
        id=p.get("id", ""),
        name=p.get("name", ""),
        context=ctx,
        created_at=p.get("created_at", ""),
    )


@router.get("", response_model=list[ScenarioPresetResponse])
async def list_presets(request: Request) -> list[ScenarioPresetResponse]:
    """查询所有场景预设."""
    store = _preset_store(request.state.user_id)
    presets = await safe_memory_call(store.read(), "presets(list)")
    return [_dict_to_preset_response(p) for p in presets]


@router.post("", response_model=ScenarioPresetResponse)
async def save_preset(
    req: SavePresetRequest, request: Request
) -> ScenarioPresetResponse:
    """保存场景预设."""
    user_id = request.state.user_id
    store = _preset_store(user_id)
    preset = ScenarioPreset(name=req.name, context=req.context)
    await safe_memory_call(store.append(preset.model_dump()), "presets(save)")
    return _dict_to_preset_response(preset.model_dump())


@router.delete("/{preset_id}")
async def delete_preset(preset_id: str, request: Request) -> dict[str, bool]:
    """删除场景预设."""
    store = _preset_store(request.state.user_id)
    presets = await safe_memory_call(store.read(), "presets(read_for_delete)")
    new_presets = [p for p in presets if p.get("id") != preset_id]
    if len(new_presets) == len(presets):
        return {"success": False}
    await safe_memory_call(store.write(new_presets), "presets(delete)")
    return {"success": True}
