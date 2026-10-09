# 生物实验智学助手

平台名称：**生物实验智学助手**。模块一：**生物功能图谱**——探索基因、蛋白与代谢物的通路关联。模块二：**电泳异常分析**——结合实验记录与对照结果分析电泳异常，通过教师反馈和复测验证改进判断。

产品名称：生物实验智学助手

副标题：面向本科生物实验教学的知识探索与智能复盘工具

模块：生物功能图谱；电泳异常分析（PCR 与电泳）

面向本科实验教学：独立初判 → 追问补证 → 教师复核 → 学生修订 → 验证计划 → 实际复测。主要面向每班 20 多人的本科生物实验教学，另按 AI+高等教育—AI+教学整理参赛材料；真实课堂效果尚待验证。

文档核对日期：2026-10-08。已实现可选的电泳图 AI 辅助观察与师生独立核对，使用统一 DeepSeek 接口。

## 双击启动与 Windows 安装版

当前项目可双击根目录“启动生物实验智学助手.bat”；双击“创建桌面快捷方式.bat”后可从桌面启动。启动窗口自动打开浏览器，结束时点击“退出系统”。原有命令方式仍适用。

给其他电脑使用的离线安装包由 `scripts/build_windows_installer.py` 构建，包含独立 Python 运行环境。安装版把数据库、图片及配置放在用户数据目录，首次配置可在启动窗口填写。详见 [Windows安装与启动说明](docs/Windows安装与启动说明.md)。

## 本地启动

推荐 Python 3.12.14（本机验证版本）。在项目目录执行：

```powershell
python -m pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
python platform_server.py
```

访问 http://localhost:8501 。有虚拟环境时可用 `.venv\Scripts\python.exe` 替代 `python`。`streamlit_launcher.py` 按项目相对目录启动，支持移动路径。

## 内部流程验证

```powershell
.venv\Scripts\python.exe demo_runner.py
```

此命令只用于内部流程验证：使用 `data/demo/demo.db` 和独立上传目录，禁用在线 AI 请求，不读写课堂库。教师和调试入口的固定验证码仅对该隔离环境有效。历史内部案例保留在库中，不进入正式教学页面，也不提供固定案例查询或自动载入入口。

正常教学按前面的 `python platform_server.py` 启动，并配置自己的教师访问码（旧版调试入口另用调试码）。`--reset-demo` 和 `--prepare-only` 仅供后台验证，不是产品页面功能。当前不做小程序和线上部署。统一网页已迁入 Vue 3 + TypeScript + FastAPI，保留旧版 Streamlit 入口。

## 统一平台与旧版入口

新平台使用 Vue 3 + TypeScript 网页、FastAPI 接口及 SQLite；知识数据为独立只读资源。`experiment_business.py` 与原版共用诊断、归一化和报告逻辑，`teaching_platform/` 负责服务端权限、任务知识关联与接口。品牌集中在 `teaching_platform/config.py`。

完整用法见 [统一教学平台使用说明](docs/统一教学平台使用说明.md)。旧版可双击“启动旧版实验复盘.bat”或运行 `python -m streamlit run app.py`；原生物功能图谱不修改。知识数据构建使用 `python scripts/build_knowledge.py`，从原工作簿重建先运行 `python scripts/build_knowledge_source.py --input 工作簿路径`。

验证使用 `python -m unittest discover -s tests -v`；浏览器验收脚本 `scripts/verify_unified_browser.cjs` 仅连接隔离服务，禁止直接连接课堂环境。安装前先构建网页，再运行 `python scripts/build_windows_installer.py`。

## 学生与教师流程

1. 学生填写现象、对照和自己的初判。参数初始空白，对照默认未观察；需要时补课程、班级、匿名组号、模板浓度和类型、反应体积、目标片段、推荐退火温度及聚合酶。
2. 可上传有效 PNG/JPG 凝胶图（不超过 10 MB）并填写人工泳道说明。完成独立初判后，可主动使用“电泳图 AI 辅助观察”，预览发送区域、人工指定泳道身份，再逐项核对。图像候选与人工核对单独保存，均不自动进入诊断规则；缺图不会单独降低证据支持程度。
3. AI 或本地整理提供候选线索，学生须逐项手动确认已发生的事实，猜测、疑问和否定不直接影响排序。
4. 系统给出 Top3 排查建议；保存私有查询码，回答定向追问。补证后更新同一案例排序并保留初判快照。
5. 教师复核原因，注明经验复核、原始记录支持、复测验证或原因待核实；人工教学评价可选，不自动给学生评分。
6. 学生凭查询码找回反馈，提交原因修订及证据。教师改变反馈后可针对新版本再次修订，历次内容保留。
7. 学生提交假设、变量、对照、预期结果及解释五项验证计划，教师可反馈。计划不算复测结果。

看板默认只统计真实课堂；内部模拟案例和规则回归记录从正式页面排除，未标注的历史记录可另行核查。阶段完成数有明确分母。教师一致率不等于实验准确率或学生能力提升。

## 配置与数据

- `DEEPSEEK_API_KEY` 可选，文字和图片统一使用 DeepSeek 官方 `https://api.deepseek.com` 与 `deepseek-flash`。从根目录 `.env` 或 `.streamlit/secrets.toml` 读取；旧 `BIGMODEL_*` 和其他模型名/地址配置不再用于请求。
- `DEEPSEEK_VISION_ENABLED=false` 可关闭在线图像观察；已保存的候选与人工核对仍可查看。默认开启，无 Key 时按钮不可用。
- `TEACHER_ACCESS_CODE`、`DEV_ACCESS_CODE` 分别保护课堂教师和调试入口，通过环境变量或 Streamlit secrets 配置。勿以固定演示码保护真实数据。
- `PCR_DIAGNOSIS_DB_PATH` 默认 `data/app.db`；`PCR_DIAGNOSIS_UPLOAD_DIR` 默认 `uploads`。
- `course_presets.json` 已加入教师提供的 pET-28a(+) 质粒方案，未知项保留为空；教师可在课程方案工作区保存版本。

文字模型只润色追问或建议候选事实，排序由规则执行。文字请求超时 8 秒，图片请求超时 30 秒，均关闭 SDK 自动重试并限制输出，显式关闭默认思考模式。AI 图像原始候选、学生核对、教师图像复核分别追加版本；重新识别会产生新调用，旧版本只读，不增加教师原因反馈版本。相同图片、发送设置与泳道身份的已保存观察可复用，页面重绘不自动调用。本地演示不使用接口。

AI 模式会将必要文字或处理后的图片发送到 DeepSeek；图像请求只包含匿名泳道映射及去元数据图片，不发送查询码和完整案例记录。图片中可见的身份信息需由使用者裁剪去除。没有 Key、接口失败或关闭识别时，原有人工教学流程照常使用。使用步骤和限制见 [电泳图辅助观察使用说明](docs/电泳图AI辅助观察使用说明.md)。

数据库保存查询码的 SHA256 摘要；遗失查询码后不能找回学生视图。旧记录无查询码时仍可教师查看。首次升级旧库先生成 `app.db.before-competition-upgrade.bak` 再扩展字段；增加图像表前对已有库生成 `app.db.before-gel-observation.bak`，新增教学表前生成 `app.db.before-teaching-workflow.bak`，不删除旧记录。历史详情、看板及报告读取保存结果，不按新规则自动改写。规则及归一化代码的哈希随新案例保存，旧记录缺版本明确标记。

课堂模式禁用清空历史和上传目录。演示清理须同时满足固定演示路径、模式标记、库中全部为模拟或回归记录。

## 文件与验证

- `experiment_business.py` 共享纯业务与报告，`core.py` 适配旧页面；`case_storage.py` 快照、迁移、版本与验证计划。
- `diagnosis_normalization.py`、`diagnosis_rule_engine_v2.py` 输入归一化与排序。
- `rules.csv` 40 条启用主规则；`rule_combos.csv` 2 条组合。同原因基础分取最强，不重复累加。
- `evidence_support.py` 事实筛选、原因 ID、规则哈希、参数校验与阶段计数。
- `followup_agent.py` 有边界的追问与候选整理；`demo_cases.json`、`demo_runner.py` 隔离演示。
- `ai_config.py` 固定国内模型配置；`gel_image_assistant.py` 受限观察与图像处理；`gel_image_ui.py` 学生核对与教师图像复核。
- [科学边界](RULE_AUDIT.md)、[参赛材料入口](docs/competition/README.md)。

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

2026-10-09 统一平台回归：90 项测试通过，包含 20 人并发提交与上传。五种屏幕宽度的真实浏览器交互脚本为 `node scripts/verify_unified_browser.cjs`，仅连接隔离服务。旧版完整页面流程脚本为 `python scripts/verify_competition_ui.py`，使用临时库与受控图像响应；主动在线联调脚本为 `python scripts/verify_deepseek_live.py`，会发送固定匿名文本与程序生成图片并产生用量。两者均不能证明真实课堂图片识别准确率。

配置示例见 `.env.example` 和 `.streamlit/secrets.toml.example`，保留已有入口码，勿提交真实密钥。统一网页顶部显示集中配置的产品名和副标题，提供生物功能图谱、实验复盘和教师工作区。旧版模块标识仅保留在其正文和报告中。

依赖锁定为本机验证版本。视觉规范见 [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)，本次新增流程核验见参赛目录。根目录旧 DOCX 保留原稿，但不作为当前技术口径。

## 六项教学功能（2026-10-08）

已增加课堂任务与三阶段人工评价、教师先独立复核再查看建议、课程方案版本与依据卡片、实际复测与教师解释、班级问题及受限 AI 教学建议、独立图像评估。教师登录后在“教师工作区”切换入口，默认进入独立复核；学生可加入任务、提交新案例原稿并追加实际复测。详细步骤与限制见 [教学功能升级使用说明](docs/教学功能升级使用说明.md)。

已依据教师提供的信息加入 pET-28a(+) 质粒 PCR 课程预设：每管 50 μL、模板 1 μL、30 循环及 50–63℃梯度程序；原液浓度、目标片段、最佳退火温度、试剂品牌和阳性/NTC 设置仍待确认。

独立判断、课程方案、复测解释、过程评价和图像参考/候选分别留痕。实际课堂效果与真实图像表现仍待采集，不自动给分或确定原因。

六项交互回归：`python scripts/verify_teaching_ui.py`，不调用外部接口。新模块为 `teaching_workflow.py`（存储与受限业务）及 `teaching_ui.py`（复用课堂访问验证的教学面板）。
