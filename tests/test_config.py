import os

import yaml

from edgeguard import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_overrides_deep_merge(tmp_path, monkeypatch):
    over = tmp_path / "o.yaml"
    over.write_text("cse: {base_url: http://mobius:7579}\nmec: {notify_url: http://mec:9090/notify}\n")
    monkeypatch.setenv("EDGEGUARD_OVERRIDES", str(over))
    cfg = config.load(os.path.join(ROOT, "config", "site.yaml"))
    assert cfg["cse"]["base_url"] == "http://mobius:7579"
    assert cfg["cse"]["origin"] == "SEdgeGuard"                 # untouched keys survive
    assert cfg["risk"]["t_warn"] == 4.88 and cfg["risk"]["truck_priority"] is True   # robust policy (sim/train_multi.py)


def test_compose_overrides_only_change_deployment_keys():
    over = yaml.safe_load(open(os.path.join(ROOT, "deploy", "compose-overrides.yaml")))
    assert "risk" not in over and "rate_control" not in over    # the tuned policy comes from site.yaml
    assert over["cse"]["base_url"].startswith("http://mobius:")


def test_override_layers_in_order_and_missing_ones_skipped(tmp_path, monkeypatch):
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text("cse: {base_url: http://mobius:7579}\nmec_services: {enabled: false}\n")
    b.write_text("mec_services: {enabled: true, base_url: https://try-mec.etsi.org/sbx/mep1}\n")
    monkeypatch.setenv("EDGEGUARD_OVERRIDES", f"{a},{tmp_path / 'missing.yaml'},{b}")
    cfg = config.load(os.path.join(ROOT, "config", "site.yaml"))
    assert cfg["cse"]["base_url"] == "http://mobius:7579"
    assert cfg["mec_services"]["enabled"] is True and cfg["mec_services"]["location_api"] == "location/v3"
