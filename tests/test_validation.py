import pandas as pd
import pytest

from src import config
from src.validation import validate_master

pytestmark = pytest.mark.skipif(
    not (config.DATA / "master_dataset.csv").exists(),
    reason="generated master dataset is not included in the code/reports repository",
)


def test_master_dataset_passes_pandera():
    df = pd.read_csv(config.DATA / "master_dataset.csv")
    report = validate_master(df)
    assert report["passed"], report["errors"][:3]
