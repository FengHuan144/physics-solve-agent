# -*- coding: utf-8 -*-
"""验证器 · L1 计算（sympy 回代）+ L2 量纲（pint）。

T12a 交付物。边界写在 ``说明.md``：

- 不做视觉前置（caption 管线 / VLM 是 T12b）
- 不改 Schema（checks[] 四字段、status 四值、21 条错误码是既定契约）
- 不判「建模对不对」（方程建错但自洽、量纲也对，L1/L2 抓不到，那是 L5）
"""

__version__ = "1.0.0"
