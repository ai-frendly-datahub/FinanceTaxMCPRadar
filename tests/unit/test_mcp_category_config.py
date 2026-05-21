from __future__ import annotations

from pathlib import Path

from radar.analyzer import apply_entity_rules
from radar.collector import parse_markdown_section_items
from radar.config_loader import load_category_config, load_category_quality_config
from radar.models import Article, CategoryConfig, Source
from radar_core.ontology import annotate_articles_with_ontology


def _category_name() -> str:
    configs = sorted(Path("config/categories").glob("*.yaml"))
    assert len(configs) == 1
    return configs[0].stem


def _seed_source(category: CategoryConfig) -> Source:
    seeds = [source for source in category.sources if source.type == "github_readme_section"]
    assert len(seeds) == 1
    return seeds[0]


def _mcp_source(category: CategoryConfig, repository: str) -> Source:
    return next(
        source
        for source in category.sources
        if source.type == "mcp_server" and source.config.get("repository") == repository
    )


def test_mcp_category_config_uses_readme_section_source() -> None:
    category = load_category_config(_category_name())

    source = _seed_source(category)
    assert source.type == "github_readme_section"
    assert (
        source.url
        == "https://raw.githubusercontent.com/darjeeling/awesome-mcp-korea/main/README.md"
    )
    assert source.section
    assert source.trust_tier == "T4_community"
    assert source.collection_tier == "C1_static_list"
    assert source.content_type == "mcp_directory"
    assert {entity.name for entity in category.entities} >= {
        "MCPDomain",
        "Provider",
        "Capability",
        "RiskScope",
        "ProjectHealth",
    }


def test_mcp_category_config_matches_section_entries() -> None:
    category = load_category_config(_category_name())
    seed_source = _seed_source(category)
    section = seed_source.section
    markdown = f"""
### {section}

**[example-mcp](https://github.com/example/example-mcp)** - {section} MCP server with API search tools.

### Other Section

**[other-mcp](https://github.com/example/other-mcp)** - Another MCP server.
"""

    items = parse_markdown_section_items(markdown, section)
    assert len(items) == 1

    article = Article(
        title=items[0]["title"],
        link=items[0]["link"],
        summary=items[0]["summary"],
        source=seed_source.name,
        category=category.category_name,
    )
    analyzed = apply_entity_rules([article], category.entities)

    assert analyzed[0].matched_entities
    assert "MCPDomain" in analyzed[0].matched_entities
    assert "ProjectHealth" in analyzed[0].matched_entities


def test_directory_source_gets_ontology_event_model_payload() -> None:
    category = load_category_config(_category_name())
    seed_source = _seed_source(category)
    article = Article(
        title="KIS_MCP_Server",
        link="https://github.com/migusdn/KIS_MCP_Server",
        summary="한국투자증권 주식 주문 MCP 서버",
        source=seed_source.name,
        category=category.category_name,
        matched_entities={"RiskScope": ["주문"]},
    )

    annotated = annotate_articles_with_ontology(
        [article],
        repo_name="FinanceTaxMCPRadar",
        sources_by_name={seed_source.name: seed_source},
        category_name=category.category_name,
        search_from=Path(__file__),
        attach_event_model_payload=True,
    )

    ontology = annotated[0].ontology
    assert ontology["source_event_model"] == "mcp_directory_entry"
    assert ontology["event_model_id"] == "mcp.directory_entry"
    assert ontology["event_model_payload"]["source_url"] == article.link
    assert ontology["event_model_payload"]["tags"] == ["RiskScope"]


def test_mcp_server_sources_are_activation_gated() -> None:
    category = load_category_config(_category_name())
    candidates = [source for source in category.sources if source.type == "mcp_server"]
    if category.category_name != "misc_mcp":
        assert candidates

    allowed_statuses = {
        "metadata_only",
        "blocked_command_unresolved",
        "blocked_env_required",
        "blocked_runtime_timeout",
        "blocked_tool_allowlist_unresolved",
        "candidate_ready_for_fake_transport_test",
        "fake_transport_smoke_test_passed",
        "permanently_disabled_runtime_unstable",
        "real_transport_smoke_test_passed",
    }
    for source in candidates:
        assert source.collection_tier == "C4_mcp_tool"
        assert source.content_type == "mcp_tool_result"
        assert source.config["activation_status"] in allowed_statuses
        assert source.config["repository"]
        assert isinstance(source.config.get("tools", []), list)
        assert isinstance(source.config.get("resources", []), list)
        assert source.config["docs_advisory_audit_status"] == "passed"
        assert (
            source.config["docs_advisory_audit_artifact"]
            == "_workspace/2026-04-30_cycle69_mcp_docs_advisory_audit.json"
        )
        assert source.config["github_readme_present"] is True
        assert source.config["github_docs_present"] is True
        assert source.config["github_docs_paths"]
        assert source.config["github_security_advisory_access_status"].startswith("checked")
        assert source.config["github_security_advisory_count"] >= 0
        if source.config.get("command_discovery_status"):
            assert source.config["command_discovery_checked_at"]
            assert (
                source.config["command_discovery_artifact"]
                == "_workspace/2026-04-30_cycle71_mcp_command_discovery_audit.json"
            )
        if "command_or_endpoint_unresolved" in source.config.get("activation_gates", []):
            assert source.config["command_discovery_status"]
        if source.enabled:
            assert source.config["activation_status"] == "real_transport_smoke_test_passed"
            assert source.config["command"]
            assert source.config["tools"]
            assert "real_transport_smoke_test_required" not in source.config.get(
                "activation_gates", []
            )
        else:
            assert source.config["activation_status"] != "real_transport_smoke_test_passed"
        if source.config["activation_status"] != "metadata_only":
            assert source.config["activation_audited_at"]
            if source.config["activation_status"].startswith("permanently_disabled_"):
                assert source.config["disabled_reason"]
                assert source.config["activation_gates"] == []
            else:
                assert source.config["activation_gates"]


def test_mcp_category_quality_config_tracks_mcp_event_models() -> None:
    quality_config = load_category_quality_config(_category_name())
    data_quality = quality_config["data_quality"]
    assert isinstance(data_quality, dict)
    outputs = data_quality["quality_outputs"]
    assert isinstance(outputs, dict)
    assert outputs["tracked_event_models"] == [
        "mcp_directory_entry",
        "mcp_tool_result",
        "linked_repository_metadata",
        "risk_scope_signal",
    ]


def test_kis_candidate_command_is_resolved_but_env_blocked() -> None:
    category = load_category_config(_category_name())
    source = _mcp_source(category, "migusdn/KIS_MCP_Server")

    assert source.enabled is False
    assert source.config["activation_status"] == "blocked_env_required"
    assert source.config["command_discovery_status"] == "resolved_local_uv_mcp_run"
    assert source.config["command"] == "uv"
    assert source.config["args"] == [
        "run",
        "--with",
        "httpx",
        "--with",
        "mcp[cli]",
        "--with",
        "xmltodict",
        "mcp",
        "run",
        "server.py",
    ]
    assert source.config["env"] == [
        "KIS_ACCOUNT_TYPE",
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "KIS_CANO",
    ]
    assert "command_or_endpoint_unresolved" not in source.config["activation_gates"]
    assert "env_secret_documentation_required" not in source.config["activation_gates"]
    assert source.config["env_documentation_status"] == "documented_no_secret_placeholder"
    assert (
        source.config["env_documentation_artifact"]
        == "_workspace/2026-05-07_mcp_env_documentation_manifest.json"
    )
    assert "order_stock" in source.config["tools"]
    assert "order-overseas-stock" not in source.config["tools"]


def test_kis_candidate_has_fake_transport_evidence() -> None:
    category = load_category_config(_category_name())
    source = _mcp_source(category, "migusdn/KIS_MCP_Server")

    assert source.config["fake_transport_smoke_test_status"] == "passed"
    assert (
        source.config["fake_transport_smoke_test_artifact"]
        == "_workspace/2026-05-02_cycle86_financetax_migusdn_kis_fake_probe.json"
    )
    assert source.config["fake_transport_fixture"] == "fixtures/mcp/fake_migusdn_kis_mcp_server.py"
    assert "fake_transport_smoke_test_required" not in source.config["activation_gates"]
    assert "real_transport_smoke_test_required" in source.config["activation_gates"]
    assert "financial_action_possible" in source.config["risk_scope"]


def test_korea_stock_analyzer_timeout_has_monitoring_plan_deferred() -> None:
    category = load_category_config(_category_name())
    source = _mcp_source(category, "Mrbaeksang/korea-stock-analyzer-mcp")

    assert source.enabled is False
    assert source.config["activation_status"] == "permanently_disabled_runtime_unstable"
    assert source.config["runtime_timeout_confirmed_at"] == "2026-04-29T04:36:46+00:00"
    assert source.config["runtime_resolution_status"] == "permanently_disabled_runtime_unstable"
    assert (
        source.config["runtime_resolution_artifact"]
        == "_workspace/2026-05-07_mcp_runtime_blocker_resolution.json"
    )
    assert (
        source.config["runtime_resolution_reason"]
        == "stdio_initialize_timeout_confirmed_and_no_secretless_recovery_path"
    )
    assert source.config["disabled_reason"] == "upstream_stdio_initialize_timeout"
    assert (
        source.config["production_monitoring_status"]
        == "monitoring_plan_recorded_activation_deferred"
    )
    assert (
        source.config["production_monitoring_artifact"]
        == "_workspace/2026-05-07_mcp_production_monitoring_gate_closure.json"
    )
    assert source.config["production_monitoring_source"] == "activation_gate_config_review"
    assert source.config["production_monitoring_activation_condition"] == (
        "source_enabled_after_real_transport_smoke_pass_and_remaining_gates_clear"
    )
    assert "production_monitoring_required" not in source.config["activation_gates"]
    assert "reliable_stdio_initialize_required" not in source.config["activation_gates"]
    assert "upstream_startup_regression_review_required" not in source.config["activation_gates"]
    assert source.config["activation_gates"] == []
