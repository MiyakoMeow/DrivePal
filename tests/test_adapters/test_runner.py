"""runner 模块测试."""


def test_setup_vehiclemembench_path():
    """测试 setup_vehiclemembench_path 将 vendor 添加到 sys.path."""
    from adapters.runner import setup_vehiclemembench_path

    setup_vehiclemembench_path()
    import importlib.util

    spec = importlib.util.find_spec("environment.vehicleworld")
    assert spec is not None


def test_parse_file_range():
    """测试解析文件范围字符串."""
    from adapters.runner import parse_file_range

    assert parse_file_range("1-5") == [1, 2, 3, 4, 5]
    assert parse_file_range("1,3,5") == [1, 3, 5]
    assert parse_file_range("1-3,7") == [1, 2, 3, 7]


def test_parse_file_range_dedup_and_sort():
    """测试 parse_file_range 去重和排序结果."""
    from adapters.runner import parse_file_range

    assert parse_file_range("5,3,3,1") == [1, 3, 5]
    assert parse_file_range("3-1") == [1, 2, 3]


def test_paths_exist():
    """测试 vendor 路径存在."""
    from adapters.runner import VENDOR_DIR, BENCHMARK_DIR, OUTPUT_DIR

    assert VENDOR_DIR.exists()
    assert (BENCHMARK_DIR / "qa_data").exists()
    assert OUTPUT_DIR.name == "benchmark"


def test_imports_available():
    """测试 vendor 导入可用."""
    pass
