"""book-17 §3 参数策略（纯函数，可单测）：验证档低参 + 4 步加速 LoRA 默认；交付档 8 步/20 步。"""

VERIFY_TIER = {"resolution": "360p", "seconds": 5}
DELIVERY_TIER = {"r2v_lora": "ref2v_8step", "non_r2v_lora": None, "steps": 8}


def default_lora_for_stage(stage: str):
    """验证档默认加速 LoRA：t2v/i2v/flf2v→fl2v_4step；r2v→ref2v_4step；未知→None（不加速）。"""
    if stage in ("t2v", "i2v", "flf2v"):
        return "fl2v_4step"
    if stage == "r2v":
        return "ref2v_4step"
    return None


def delivery_lora_for_stage(stage: str):
    """交付档（用户要求精品/正式/高清）：r2v→ref2v_8step(v1.0 768p)；其余→None=20 步默认精度。"""
    if stage == "r2v":
        return "ref2v_8step"
    return None


def default_params_for_stage(stage: str) -> dict:
    """验证档默认参数包：360p + 5s + 4 步 LoRA（若该阶段有对应档）。"""
    d = dict(VERIFY_TIER)
    lora = default_lora_for_stage(stage)
    if lora:
        d["lora"] = lora
    return d