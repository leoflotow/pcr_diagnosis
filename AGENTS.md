# AGENTS.md

## 项目与边界

生物实验智学助手，统一 Vue/FastAPI 教学平台；旧版 Streamlit 入口保留。副标题：面向本科生物实验教学的知识探索与智能复盘工具。模块：生物功能图谱、电泳异常分析（PCR 与电泳）。独立初判→补证→教师复核→学生修订→验证计划。当前参赛方向为 AI+高等教育—AI+教学，无真实课堂效果材料，勿编造成效。小程序和网页部署暂不实施。

## 运行与验证

```powershell
python -m pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
python platform_server.py
# 旧版回退及内部验证
python -m streamlit run app.py
python demo_runner.py
python -m unittest discover -s tests -v
```

演示使用 8513 端口、固定独立库 `data/demo/demo.db`。课堂库 `data/app.db` 与 `uploads/` 必须保留。测试用临时库，勿以课堂数据做清理或写入测试。不要读取或打包 `.env`、真实 secrets、数据库和学生照片。

## 架构与业务约束

- `app.py` 导航入口；`core.py` 共享业务与报告；每页导入共享模块。
- `case_storage.py` 迁移、首次升级备份、快照、教师和学生版本历史、验证计划。
- `evidence_support.py` 事实过滤、精确原因归一化与稳定 ID、规则哈希、参数和阶段计数。
- `diagnosis_normalization.py` 归一化 8 类现象、分型对照与手动事实线索。
- `diagnosis_rule_engine_v2.py`：40 条主规则、2 条独立补充证据组合；同原因基础分取最强，不重复计分。`rules_v2.csv` 是保守后备。
- `followup_agent.py`：最多三个观察问题，另保留操作入口。AI 润色与建议，学生手动确认后影响排序。
- `course_presets.json`：教师提供的 pET-28a(+) 方案，每管50 μL、模板1 μL、梯度50–63℃；浓度、片段、最佳温度、品牌和阳性/NTC设置仍未知。不能推定实际质量。
- `pages/` 学生、教师与开发页面；`docs/competition/` 当前参赛材料，根目录旧 DOCX 不作当前口径。

历史查看只读快照或保存字符串，不重新诊断、不调用模型。新案例保存原始输入、确认线索、规则版本和初判/补证结果。教师修改反馈升版本，旧记录保留；单纯评分和来源更新不要求学生重复修订。修订须私有查询码及对应版本。

区分真实课堂、模拟、回归、未标注来源。看板默认真实课堂。人工评价、阶段完成率、教师一致率、能力迁移与复测验证分别表述。图像 AI 只观察，原始候选、学生核对、教师图像复核独立留痕，均不直接进入诊断规则、原因评分或成绩。身份由人工指定，未知不补零，旧图与旧观察不能套用新设置。体积与绝对温度不证明模板不足或温度异常。

页面用于正式教学，不显示比赛、演示、demo 或虚拟数据相关说明，不提供内部案例载入与环境重置入口；内部示例和规则校验记录不进入课堂页面，历史来源不改写。

共用顶部导航仅显示产品名与副标题，当前模块仍保留于首页正文和报告；不要重新添加已删除的导航模块行。功能说明更新须同步对应 PDF 与源码支持 ZIP，历史审查和设计稿明确标为历史，不将旧验收冒充本次实测。

保持中文 UI 和注释，精准修改，沿用现有设计。UI 完成须新截图或 DOM 尺寸证据；HTTP 200 或编译不代表视觉通过。

## API

所有 AI 请求使用 `ai_config.py` 中的 DeepSeek 官方 `https://api.deepseek.com` 与 `deepseek-flash`，不接受其他模型或服务商环境变量覆盖。`DEEPSEEK_API_KEY` 可选，从环境或 secrets 读取，文字与图片共用；旧 `BIGMODEL_*` 不再使用。文字超时 8 秒、图片超时 30 秒、重试 0，显式关闭思考并限制输出。无接口可本地整理，独立演示禁用接口。图像请求须主动点击且确认发送区域，图片只发送匿名映射与处理副本。课堂教师/调试码来自环境或 secrets；固定演示码只对固定演示路径有效。

## 教学扩展约束

`teaching_workflow.py` 管理任务、过程评价、独立复核、方案版本、复测、受限教学建议和图像评估；`teaching_ui.py` 提供工作区。默认先独立复核；进入常规复核将已载入案例标为看过建议，共用访问码不支持教师个人盲法身份。改变独立判断必须写理由。任务发布冻结题目与方案，修订评价对应反馈版本。复测须有保存计划及私有查询码，不覆盖原图。教学建议只发送聚合数量并从固定动作选择。图像参考先于模型保存，同原图族不能跨集合，争议/错配/未知分别统计；数量差不宣称定位漏检。新交互回归 `python scripts/verify_teaching_ui.py`，只用临时库和生成图片。


## Windows 桌面启动与分发

`streamlit_launcher.py` 为双击入口，自动等待本机服务并打开浏览器，单实例锁防止同项目重复启动，控制窗口退出停止其自有服务。项目模式保留原库和配置；安装模式使用 `%LOCALAPPDATA%/BioLabReview` 数据与个人配置，程序在 Programs/BioLabReview，禁止把作者真实数据和 secrets 放入安装包。`desktop/` 管理快捷方式、安装和卸载脚本；PowerShell中文脚本须UTF-8 BOM。`scripts/build_windows_installer.py` 仅打包应用白名单和基础Python/项目依赖，产物在忽略的dist，临时文件在build。更新保留旧程序备份，卸载先核对路径，仅移除程序，个人数据保留。不要运行卸载脚本清理课堂数据。新验证 `tests/test_desktop_launcher.py` 与 `scripts/verify_windows_package.py` 使用隔离数据，不读取真实配置。

## 统一教学平台

新版入口 `platform_server.py`，Vue 3/TypeScript 在 frontend/，FastAPI 在 teaching_platform/，接口统一 /api/v1。纯业务抽出 experiment_business.py，core.py 保留旧页面适配，共享规则、存储和报告。旧版 app.py 仍可运行。品牌集中 teaching_platform/config.py，知识只读资源 knowledge/network.json，稳定编号不能用数组位置代替。名称和标识符自动匹配须显示待核实，禁止推断反应方向、未知物种或 PCR 片段。

服务端验证教师会话与私有查询码，图片和报告同样鉴权。任务冻结知识快照及课程方案，修改发布新版本。文本草稿限当前标签页，收藏限当前浏览器且支持导入导出。API 不信任前端已授权标记。图像只观察，主动预览同意，人工核对独立保存。

构建 npm ci --prefix frontend、npm run build --prefix frontend；运行 python platform_server.py。启动器默认本机，主动切换 LAN，不能自动改防火墙。Windows 包含已构建网页，不要求用户安装 Node.js。验证 tests/test_unified_platform.py、scripts/verify_unified_browser.cjs 和 scripts/verify_windows_package.py 只用隔离库、生成图片、BIO_CONFIG_DISABLED=1、PYTHON_DOTENV_DISABLED=1 与空密钥，不得读写课堂资源。实际手机验收与另一台电脑安装需单独如实记录。
