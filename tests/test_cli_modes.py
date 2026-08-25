from src.canarias_uni_ml.cli import build_parser


def test_cli_jobs_scrape_mode():
    parser = build_parser()
    args = parser.parse_args(["jobs", "scrape", "--limit-per-source", "10", "--max-total", "10"])
    assert args.domain == "jobs"
    assert args.jobs_command == "scrape"
    assert args.limit_per_source == 10
    assert args.max_total == 10
    assert args.region == "canarias"


def test_cli_jobs_scrape_cantabria_mode():
    parser = build_parser()
    args = parser.parse_args(["jobs", "scrape", "--region", "cantabria"])
    assert args.region == "cantabria"


def test_cli_embed_mode():
    parser = build_parser()
    args = parser.parse_args(["embed", "build", "--provider", "groq", "--dry-run"])
    assert args.domain == "embed"
    assert args.embed_command == "build"
    assert args.provider == "groq"
    assert args.dry_run is True


def test_cli_degrees_live_aneca_mode():
    parser = build_parser()
    args = parser.parse_args(
        [
            "degrees",
            "catalog",
            "--live-aneca",
            "--cycles",
            "grado,master,doctorado",
            "--limit",
            "5",
            "--with-report-text",
            "--min-inventory-completeness",
            "1.0",
            "--require-all-scoped-universities",
            "--min-description-coverage",
            "0.85",
            "--resolve-university-memory",
        ]
    )
    assert args.domain == "degrees"
    assert args.degrees_command == "catalog"
    assert args.live_aneca is True
    assert args.cycles == "grado,master,doctorado"
    assert args.limit == 5
    assert args.with_report_text is True
    assert args.min_inventory_completeness == 1.0
    assert args.require_all_scoped_universities is True
    assert args.min_description_coverage == 0.85
    assert args.resolve_university_memory is True
    assert args.http_timeout == 30


def test_cli_jobs_daemon_mode():
    parser = build_parser()
    args = parser.parse_args(
        [
            "jobs",
            "daemon",
            "--window-start",
            "22:00",
            "--window-end",
            "07:30",
            "--timezone",
            "Europe/Madrid",
            "--cooldown-minutes",
            "5",
            "--strategy",
            "scale",
            "--time-limit-minutes",
            "30",
            "--stagnation-cycles",
            "2",
            "--fail-on-stagnation",
            "--run-once",
        ]
    )
    assert args.domain == "jobs"
    assert args.jobs_command == "daemon"
    assert args.window_start == "22:00"
    assert args.window_end == "07:30"
    assert args.timezone == "Europe/Madrid"
    assert args.cooldown_minutes == 5
    assert args.strategy == "scale"
    assert args.time_limit_minutes == 30
    assert args.stagnation_cycles == 2
    assert args.fail_on_stagnation is True
    assert args.run_once is True


def test_cli_jobs_compact_mode():
    parser = build_parser()
    args = parser.parse_args(["jobs", "compact", "--db-path", "tmp/jobs.db"])
    assert args.domain == "jobs"
    assert args.jobs_command == "compact"
    assert args.db_path == "tmp/jobs.db"


def test_cli_degrees_description_alias_sets_same_flag():
    parser = build_parser()
    args = parser.parse_args(["degrees", "catalog", "--with-description-text"])
    assert args.with_report_text is True


def test_cli_degrees_live_universities_mode():
    parser = build_parser()
    args = parser.parse_args(
        ["degrees", "catalog", "--live-universities", "--cycles", "grado,master", "--skip-description-fetch"]
    )
    assert args.live_universities is True
    assert args.cycles == "grado,master"
    assert args.skip_description_fetch is True
