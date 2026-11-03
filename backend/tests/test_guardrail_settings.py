from app.core.config import Settings


def make(**kwargs) -> Settings:
    # _env_file=None keeps a developer's local .env out of these tests.
    return Settings(_env_file=None, **kwargs)


def test_defaults_match_the_agreed_caps():
    s = make()
    assert s.max_num_requests == 500
    assert s.max_concurrency == 20
    assert s.max_request_timeout_s == 10.0
    assert s.run_wall_clock_limit_s == 60.0
    assert s.max_concurrent_runs == 2
    assert s.max_active_runs_per_code == 1
    assert s.block_private_targets is True


def test_allowlist_follows_auth_unless_overridden():
    assert make(auth_enabled=True).allowlist_enforced is True
    assert make(auth_enabled=False).allowlist_enforced is False
    assert make(auth_enabled=True, target_allowlist_enabled=False).allowlist_enforced is False
    assert make(auth_enabled=False, target_allowlist_enabled=True).allowlist_enforced is True


def test_llm_benchmark_is_off_when_auth_is_on_unless_overridden():
    assert make(auth_enabled=True).llm_benchmark_active is False
    assert make(auth_enabled=False).llm_benchmark_active is True
    assert make(auth_enabled=True, llm_benchmark_enabled=True).llm_benchmark_active is True
    assert make(auth_enabled=False, llm_benchmark_enabled=False).llm_benchmark_active is False


def test_quotas_follow_auth():
    assert make(auth_enabled=True).quotas_enforced is True
    assert make(auth_enabled=False).quotas_enforced is False


def test_allowed_hosts_are_normalised_from_a_comma_separated_string():
    s = make(allowed_target_hosts=" HTTPBIN.org, demo.example.com. ,,")
    assert s.allowed_target_host_list == ["httpbin.org", "demo.example.com"]
    assert make(allowed_target_hosts="").allowed_target_host_list == []
