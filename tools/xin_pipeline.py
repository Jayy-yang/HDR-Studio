from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hdrstudio.core import (  # noqa: E402
    MODE_FUSION,
    TONE_NATURAL,
    MergeSettings,
    process_bracket,
    save_result,
)

paths = sorted((ROOT / "照片对齐训练用例" / "xin").glob("*.jpg"))
started = time.perf_counter()
result = process_bracket(
    paths,
    MergeSettings(
        mode=MODE_FUSION,
        tone=TONE_NATURAL,
        max_dim=2400,
        align=True,
        deghost=False,
        detail=1.0,
    ),
)
output = ROOT / "docs" / "xin_final.jpg"
save_result(result, output)
print("photos", len(paths))
print("time", round(result.elapsed, 2), "wall", round(time.perf_counter() - started, 2))
print("shape", result.image.shape)
print("aligned", result.aligned, "deghosted", result.deghosted)
print("warnings", result.warnings)
print("output", output)
