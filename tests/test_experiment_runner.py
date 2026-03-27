from app.experiment.test_data import TestDataGenerator


def test_seed_reproducibility():
    gen = TestDataGenerator(config_dir="config")
    cases_a = gen.generate_test_cases(count=5, seed=42)
    cases_b = gen.generate_test_cases(count=5, seed=42)
    assert [c["input"] for c in cases_a] == [c["input"] for c in cases_b]


def test_seed_produces_different_without_seed():
    gen = TestDataGenerator(config_dir="config")
    cases_a = gen.generate_test_cases(count=5, seed=42)
    cases_b = gen.generate_test_cases(count=5, seed=99)
    inputs_a = [c["input"] for c in cases_a]
    inputs_b = [c["input"] for c in cases_b]
    assert inputs_a != inputs_b or len(set(inputs_a)) == 1
