# pcr_diagnosis

PCR 电泳异常智能诊断助手。

## 功能概览

- 学生端分步提交 PCR 实验异常信息
- 系统返回 Top1 / Top2 / Top3 诊断结果
- 展示诊断依据、置信度、证据摘要和缺失信息提示
- 支持文本线索参与规则诊断
- 初判后按对照、条带位置与操作过程定向追问；学生确认补充证据后重新排序，保留前后判断供教师复核
- 学生诊断前记录自己的判断；凭私有查询码找回案例，查看教师复核，并提交一次有依据的修订
- 支持凝胶图片上传
- 教师端支持历史记录查看、筛选、统计看板和教师确认

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行项目

```bash
streamlit run app.py
```

默认访问地址：

```text
https://pcr-diagnosis.streamlit.app/
```

## 主要文件

- `app.py`：应用入口
- `core.py`：数据库、诊断逻辑和通用渲染函数
- `pages/1_学生端.py`：学生端
- `pages/2_教师端.py`：教师端
- `pages/3_开发调试端.py`：开发调试端
- `rules.csv`和`rule_combos.csv`：规则库
- `RULE_AUDIT.md`：规则的证据层级、适用边界与参考依据

## 环境变量

- `BIGMODEL_API_KEY`：自由配置
- `BIGMODEL_BASE_URL`，默认 `https://open.bigmodel.cn/api/paas/v4`
- `BIGMODEL_MODEL`，默认 `glm-5`
- `PCR_DIAGNOSIS_DB_PATH`：可选，指定 SQLite 数据库路径；未配置时使用 `data/app.db`

文本线索抽取优先调用 BigModel / GLM 接口，失败时回退本地关键词规则。未配置 `BIGMODEL_API_KEY` 时，系统会直接使用本地关键词规则抽取。
追问主题、选项和最终排序由本地程序与规则引擎控制；BigModel 可润色问句、整理操作描述中的候选线索。候选线索经学生确认后才用于再判断；未配置 API Key 时可手动确认线索。

学生在第 4 步先写判断与依据，生成结果后保存页面显示的查询码。教师复核同一案例后，学生可在原页面刷新反馈，或重新打开学生端凭查询码找回案例并提交修订。查询码只在创建该案例的页面和持有查询码的会话中显示；数据库保存的是查询码摘要，遗失后无法找回旧案例。旧记录仍可供教师查看，但没有查询码的旧记录不支持学生跨会话找回。
# 视觉体系与验收

当前页面采用统一的暖白实验工作台设计，布局来自方案 1，配色来自方案 3。设计 token、状态和响应式规范见 [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)，实际截图比较和验收记录见 [design-qa.md](design-qa.md)。全站样式由 `ui_design.css` 和 `ui_design.py` 统一维护。
