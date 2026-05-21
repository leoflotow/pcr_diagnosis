# pcr_diagnosis

PCR 电泳异常智能诊断助手。

## 功能概览

- 学生端分步提交 PCR 实验异常信息
- 系统返回 Top1 / Top2 / Top3 诊断结果
- 展示诊断依据、置信度、证据摘要和缺失信息提示
- 支持文本线索参与规则诊断
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

## 环境变量

- `BIGMODEL_API_KEY`：自由配置
- `BIGMODEL_BASE_URL`，默认 `https://open.bigmodel.cn/api/paas/v4`
- `BIGMODEL_MODEL`，默认 `glm-5`

如果未配置 `BIGMODEL_API_KEY`，系统会自动回退到本地关键词规则抽取。
