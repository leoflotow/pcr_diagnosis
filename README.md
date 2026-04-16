# PCR 电泳异常诊断 Demo

这是一个基于 Streamlit 的 PCR 电泳异常诊断最小可行性产品（MVP）。

## 功能简介

根据用户输入的 PCR 实验异常现象和参数，系统返回一个简单诊断结果，包括可能原因、分数和建议。

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行项目

```bash
streamlit run app.py
```

运行后，浏览器会自动打开 `http://localhost:8501` 查看应用。

## 数据库文件位置

- 路径: `data/app.db`
- 类型: SQLite 数据库
- 表名: `diagnosis_records`

每次诊断会自动保存一条记录到数据库中。

## rules.csv 作用

`rules.csv` 是诊断规则文件，包含以下字段：

- `abnormality`: 实验异常现象
- `cause`: 异常原因
- `positive_control_normal`: 阳性对照是否正常
- `negative_control_band`: 阴性对照是否有带
- `min_template` / `max_template`: 模板量范围
- `min_temp` / `max_temp`: 退火温度范围
- `min_cycles` / `max_cycles`: 循环数范围
- `score`: 匹配分数
- `suggestion`: 建议操作

用户可以根据实际需求修改规则文件来调整诊断逻辑。

## 环境变量配置

项目使用以下环境变量来配置 BigModel（智谱）API：

- `BIGMODEL_API_KEY`：BigModel API 密钥（必须配置才能使用 AI 文本抽取）
- `BIGMODEL_BASE_URL`：BigModel API 基础 URL（默认：`https://open.bigmodel.cn/api/paas/v4`）
- `BIGMODEL_MODEL`：使用的模型名称（默认：`glm-5`）

### 配置说明

**Windows PowerShell 配置示例：**

```powershell
# 设置环境变量
$env:BIGMODEL_API_KEY = "your-api-key-here"
$env:BIGMODEL_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
$env:BIGMODEL_MODEL = "glm-5"

# 验证设置
Get-ChildItem Env:BIGMODEL_*
```

**重要说明：**
- Codex 使用默认 OpenAI 配置
- 项目业务中的 BigModel 使用 BIGMODEL_* 私有变量
- 两者互不影响
- 如果未配置 `BIGMODEL_API_KEY`，系统会自动回退到本地规则抽取