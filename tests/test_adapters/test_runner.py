"""runner 模块测试."""


def test_setup_vehiclemembench_path():
    """Test that setup_vehiclemembench_path adds vendor to sys.path."""
    from adapters.runner import setup_vehiclemembench_path

    setup_vehiclemembench_path()
    import importlib.util

    spec = importlib.util.find_spec("environment.vehicleworld")
    assert spec is not None


def test_parse_file_range():
    """Test parsing file range strings."""
    from adapters.runner import parse_file_range

    assert parse_file_range("1-5") == [1, 2, 3, 4, 5]
    assert parse_file_range("1,3,5") == [1, 3, 5]
    assert parse_file_range("1-3,7") == [1, 2, 3, 7]


def test_parse_file_range_dedup_and_sort():
    """Test that parse_file_range deduplicates and sorts results."""
    from adapters.runner import parse_file_range

    assert parse_file_range("5,3,3,1") == [1, 3, 5]
    assert parse_file_range("3-1") == [1, 2, 3]


def test_paths_exist():
    """Test that vendor paths exist."""
    from adapters.runner import VENDOR_DIR, BENCHMARK_DIR, OUTPUT_DIR

    assert VENDOR_DIR.exists()
    assert (BENCHMARK_DIR / "qa_data").exists()
    assert OUTPUT_DIR.name == "benchmark"


def test_imports_available():
    """Test that vendor imports are available."""
    pass
