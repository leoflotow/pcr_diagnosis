# 生物实验智析助手

产品名称：生物实验智析助手

副标题：面向本科生物实验教学的智能复盘工具

当前模块：PCR 与电泳实验复盘

面向本科实验教学：独立初判 → 追问补证 → 教师复核 → 学生修订 → 验证计划。当前按 AI+高等教育—AI+教学准备参赛；真实课堂效果尚待验证。

## 本地启动

推荐 Python 3.12.14（本机验证版本）。在项目目录执行：

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

访问 http://localhost:8501 。有虚拟环境时可用 `.venv\Scripts\python.exe` 替代 `python`。`streamlit_launcher.py` 按项目相对目录启动，支持移动路径。

## 独立参赛演示

```powershell
.venv\Scripts\python.exe demo_runner.py
```

访问 http://127.0.0.1:8513 。教师码 `demo-teacher`、调试码 `demo-dev`，三个案例查询码 `demo-case-1`、`demo-case-2`、`demo-case-3`。固定码仅对独立演示库有效。演示明确标为模拟、禁用 AI 请求，使用 `data/demo/demo.db` 与独立上传目录；课堂库不参与。

`--reset-demo` 恢复三个固定案例，遇到非模拟记录会拒绝清理；`--prepare-only` 只准备数据。当前不做小程序、线上部署和平台迁移。

## 学生与教师流程

1. 学生填写现象、对照和自己的初判。参数初始空白，对照默认未观察；需要时补课程、班级、匿名组号、模板浓度和类型、反应体积、目标片段、推荐退火温度及聚合酶。
2. 可上传有效 PNG/JPG 凝胶图（不超过 10 MB）并填写人工泳道说明。系统不自动识图，缺图不会单独降低证据支持程度。
3. AI 或本地整理提供候选线索，学生须逐项手动确认已发生的事实，猜测、疑问和否定不直接影响排序。
4. 系统给出 Top3 排查建议；保存私有查询码，回答定向追问。补证后更新同一案例排序并保留初判快照。
5. 教师复核原因，注明经验复核、原始记录支持、复测验证或原因待核实；人工教学评价可选，不自动给学生评分。
6. 学生凭查询码找回反馈，提交原因修订及证据。教师改变反馈后可针对新版本再次修订，历次内容保留。
7. 学生提交假设、变量、对照、预期结果及解释五项验证计划，教师可反馈。计划不算复测结果。

看板默认只统计真实课堂；模拟、规则回归与未标注数据分别筛选。阶段完成数有明确分母。教师一致率不等于实验准确率或学生能力提升。

## 配置与数据

- `BIGMODEL_API_KEY` 可选；`BIGMODEL_BASE_URL` 默认 `https://open.bigmodel.cn/api/paas/v4`；`BIGMODEL_MODEL` 默认 `glm-5`。
- `TEACHER_ACCESS_CODE`、`DEV_ACCESS_CODE` 分别保护课堂教师和调试入口，通过环境变量或 Streamlit secrets 配置。勿以固定演示码保护真实数据。
- `PCR_DIAGNOSIS_DB_PATH` 默认 `data/app.db`；`PCR_DIAGNOSIS_UPLOAD_DIR` 默认 `uploads`。
- `course_presets.json` 中课程条件暂缺，保留待补充；勿以模拟参数替代真实方案。

模型只润色追问或建议候选事实，排序由规则执行。单次请求超时 8 秒，关闭 SDK 自动重试；实际网络故障耗时仍需目标环境验证。本地演示不使用接口。AI 模式会把填写的描述发往配置的模型服务，教学记录用匿名编号，避免输入姓名、学号和联系方式。

数据库保存查询码的 SHA256 摘要；遗失查询码后不能找回学生视图。旧记录无查询码时仍可教师查看。首次升级旧库先生成 `app.db.before-competition-upgrade.bak` 再扩展字段，不删除旧记录。历史详情、看板及报告读取保存结果，不按新规则自动改写。规则及归一化代码的哈希随新案例保存，旧记录缺版本明确标记。

课堂模式禁用清空历史和上传目录。演示清理须同时满足固定演示路径、模式标记、库中全部为模拟或回归记录。

## 文件与验证

- `core.py` 共享业务与报告；`case_storage.py` 快照、迁移、版本与验证计划。
- `diagnosis_normalization.py`、`diagnosis_rule_engine_v2.py` 输入归一化与排序。
- `rules.csv` 40 条启用主规则；`rule_combos.csv` 2 条组合。同原因基础分取最强，不重复累加。
- `evidence_support.py` 事实筛选、原因 ID、规则哈希、参数校验与阶段计数。
- `followup_agent.py` 有边界的追问与候选整理；`demo_cases.json`、`demo_runner.py` 隔离演示。
- [科学边界](RULE_AUDIT.md)、[参赛材料入口](docs/competition/README.md)。

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

依赖锁定为本机验证版本。视觉规范见 [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)，本次新增流程核验见参赛目录。根目录旧 DOCX 保留原稿，但不作为当前技术口径。
