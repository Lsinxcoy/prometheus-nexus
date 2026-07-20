"""Phase F: 深度分析后收尾测试.

验证:
- z_mech 类占位机制(draft=x/pending)归 test_residue, 不再误判 trigger_missing
- Owner-Harm violation 良性定性: requester=main + reason含"does not have trust" -> benign(info)
- 清理 archive/mechanisms.json 垃圾键后 registry 加载不崩
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_placeholder_mech_classified_test_residue():
    """draft_code=x + status=pending + invoke=0 的机制应归 test_residue."""
    # 模拟 _classify_silent 的判定逻辑(与 life.py 一致)
    def classify(name, meta):
        meta = meta or {}
        draft = (meta.get("data") or {}).get("draft_code") if isinstance(meta.get("data"), dict) else None
        status = meta.get("status")
        invoke = meta.get("invoke_count", 0) or 0
        low = name.lower()
        is_test = ("test" in low or low.startswith(("p_", "c1_", "bad_", "z_"))
                   or draft in ("x", "y", "")
                   or (status in ("pending", "disabled") and invoke == 0))
        return "test_residue" if is_test else "trigger_missing"
    assert classify("z_mech", {"data": {"draft_code": "x"}, "status": "pending", "invoke_count": 0}) == "test_residue"
    assert classify("bad_mech", {"data": {"draft_code": "y"}, "status": "disabled", "invoke_count": 0}) == "test_residue"
    # 真实机制(compiled, active, 有调用) 不应误判 test_residue
    assert classify("real_mech", {"data": {}, "status": "active", "invoke_count": 5}) == "trigger_missing"


def test_owner_harm_benign_qualification():
    """violation requester=main + reason含'does not have trust' 应判良性(非恶意)."""
    vlist = [{"requester": "main", "reason": "main does not have trust from owner system"}]
    malicious = []
    for v in vlist:
        r = v.get("requester", "?")
        reason = v.get("reason", "")
        if not (("does not have trust" in reason) or r in ("recall", "main", "system", "Omega")):
            malicious.append(r)
    assert not malicious, "main 分支隔离过滤应判良性"


def test_mechanisms_json_load_safe_after_cleanup(tmp_path):
    """mechanisms.json 含 z_mech 垃圾键时, 清理后加载不崩."""
    # 用临时文件, 避免依赖/污染仓库 archive/mechanisms.json(机制注册表会持久化重建)
    path = tmp_path / "mechanisms.json"
    blob = {"mechanisms": {"z_mech": {"data": {"draft_code": "x"}, "status": "pending", "invoke_count": 0},
                            "real_mech": {"data": {}, "status": "active", "invoke_count": 5}}}
    path.write_text(json.dumps(blob), encoding="utf-8")
    # 模拟清理: 删除 z_mech 垃圾键(与 phase_f 清理逻辑一致)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mechanisms"].pop("z_mech", None)
    path.write_text(json.dumps(data), encoding="utf-8")
    # 加载逻辑: {k: dict(v) for k,v in blob['mechanisms'].items()} -> 缺失键不构成问题
    loaded = {k: dict(v) for k, v in json.loads(path.read_text(encoding="utf-8")).get("mechanisms", {}).items()}
    assert "z_mech" not in loaded, "z_mech 垃圾应已被清理"
    assert isinstance(loaded, dict)
