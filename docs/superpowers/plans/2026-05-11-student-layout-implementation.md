# Student Layout Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the student page into a focused 4-step wizard layout while preserving the existing diagnosis workflow and data handling.

**Architecture:** Keep the Streamlit page architecture unchanged: `pages/1_学生端.py` remains responsible for the student workflow, and `core.py` remains responsible for shared styling helpers. The implementation changes rendering structure and CSS only; diagnosis, persistence, image handling, and report export stay on their current code paths.

**Tech Stack:** Python, Streamlit, SQLite, local CSS injected through `st.markdown(..., unsafe_allow_html=True)`.

---

## File Structure

- Modify `D:\pcr_diagnosis\core.py`
  - Responsibility: shared visual styling for cards, buttons, progress, and the new student wizard classes.
  - Scope: add CSS classes inside `apply_common_styles()` only.

- Modify `D:\pcr_diagnosis\pages\1_学生端.py`
  - Responsibility: student-facing 4-step workflow.
  - Scope: remove the large "操作步骤" tile block, add a compact demo-data toolbar, upgrade the current-step header to a stepper, and tighten the review/results layout.

- No new runtime files.
- No database, rules, AI extraction, upload, or report-generation changes.

---

### Task 1: Add Focused Wizard CSS

**Files:**
- Modify: `D:\pcr_diagnosis\core.py`

- [ ] **Step 1: Add student wizard CSS classes**

In `D:\pcr_diagnosis\core.py`, inside `apply_common_styles()`, add the following CSS block after the existing `.pcr-step-desc` rule and before `[data-testid="stMetric"]`:

```css
        .pcr-student-toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            border: 1px solid var(--pcr-border);
            border-radius: 18px;
            background: rgba(255, 255, 255, 0.92);
            padding: 0.95rem 1rem;
            margin-bottom: 1rem;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
        }

        .pcr-student-toolbar-title {
            margin: 0 0 0.18rem 0;
            color: var(--pcr-text);
            font-weight: 700;
            font-size: 1rem;
            line-height: 1.35;
        }

        .pcr-student-toolbar-desc {
            margin: 0;
            color: var(--pcr-muted);
            font-size: 0.9rem;
            line-height: 1.55;
        }

        .pcr-stepper-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.85rem 0 0.85rem 0;
        }

        .pcr-stepper-item {
            border: 1px solid var(--pcr-border);
            border-radius: 14px;
            background: #ffffff;
            padding: 0.78rem 0.85rem;
            min-height: 5.25rem;
        }

        .pcr-stepper-item.active {
            border-color: rgba(29, 78, 216, 0.42);
            background: linear-gradient(180deg, #eff6ff 0%, #ffffff 100%);
            box-shadow: 0 10px 24px rgba(29, 78, 216, 0.1);
        }

        .pcr-stepper-item.done {
            border-color: rgba(22, 163, 74, 0.28);
            background: #f0fdf4;
        }

        .pcr-stepper-index {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.55rem;
            height: 1.55rem;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.1);
            color: var(--pcr-primary);
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.46rem;
        }

        .pcr-stepper-item.done .pcr-stepper-index {
            background: #dcfce7;
            color: #166534;
        }

        .pcr-stepper-item.active .pcr-stepper-index {
            background: var(--pcr-primary);
            color: #ffffff;
        }

        .pcr-stepper-title {
            color: var(--pcr-text);
            font-weight: 700;
            font-size: 0.92rem;
            line-height: 1.35;
            margin-bottom: 0.25rem;
        }

        .pcr-stepper-status {
            color: var(--pcr-muted);
            font-size: 0.78rem;
            line-height: 1.45;
        }

        .pcr-current-step-summary {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 0.25rem;
        }

        .pcr-current-step-chip {
            flex: 0 0 auto;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.1);
            color: var(--pcr-primary);
            border: 1px solid rgba(59, 130, 246, 0.2);
            padding: 0.2rem 0.7rem;
            font-size: 0.78rem;
            font-weight: 800;
        }

        .pcr-review-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.75rem 0;
        }

        .pcr-review-item {
            border: 1px solid var(--pcr-border);
            border-radius: 14px;
            background: #ffffff;
            padding: 0.75rem 0.85rem;
        }

        .pcr-review-label {
            color: var(--pcr-muted);
            font-size: 0.78rem;
            font-weight: 700;
            margin-bottom: 0.24rem;
        }

        .pcr-review-value {
            color: var(--pcr-text);
            font-size: 0.98rem;
            font-weight: 700;
            line-height: 1.45;
            overflow-wrap: anywhere;
        }

        .pcr-result-meta-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.65rem 0 0.85rem 0;
        }

        @media (max-width: 900px) {
            .pcr-student-toolbar,
            .pcr-current-step-summary {
                display: block;
            }

            .pcr-stepper-grid,
            .pcr-review-grid,
            .pcr-result-meta-grid {
                grid-template-columns: 1fr;
            }

            .pcr-current-step-chip {
                display: inline-flex;
                margin-top: 0.55rem;
            }
        }
```

- [ ] **Step 2: Run syntax check for `core.py`**

Run:

```powershell
python -m py_compile core.py
```

Expected: command exits with code 0 and prints no syntax error.

- [ ] **Step 3: Commit CSS support**

Run:

```powershell
git add core.py
git commit -m "style: add student wizard layout classes"
```

Expected: commit succeeds and includes only `core.py`.

---

### Task 2: Replace Large Step Cards With Compact Toolbar And Stepper

**Files:**
- Modify: `D:\pcr_diagnosis\pages\1_学生端.py`

- [ ] **Step 1: Remove unused tile import**

In the import block from `core`, remove `render_info_tiles,` because the large four-card step explanation will no longer render on the student page.

Expected import excerpt:

```python
from core import (
    ABNORMALITY_OPTIONS,
    apply_common_styles,
    build_case_summary,
    diagnose,
    ensure_page_config,
    init_database,
    render_diagnosis_quality_block,
    render_card_title,
    render_page_hero,
    save_diagnosis_record,
    save_uploaded_image,
)
```

- [ ] **Step 2: Add helper for compact demo-data toolbar**

Add this function after `load_student_demo_data()`:

```python
def render_student_quick_actions():
    """渲染学生端轻量操作区，保留课堂演示入口。"""
    with st.container(border=True):
        left_col, right_col = st.columns([0.72, 0.28])
        with left_col:
            st.markdown(
                """
                <div class="pcr-student-toolbar">
                    <div>
                        <div class="pcr-student-toolbar-title">按步骤完成诊断输入</div>
                        <p class="pcr-student-toolbar-desc">
                            当前页面只在最后一步触发诊断；前面步骤可随时返回修改。
                        </p>
                    </div>
                    <span class="pcr-current-step-chip">课堂演示模式</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right_col:
            if st.button("加载演示数据", key="student_load_demo", use_container_width=True):
                load_student_demo_data()
                st.success("已加载演示数据，可按步骤继续演示。")
                st.rerun()
```

- [ ] **Step 3: Replace `render_student_wizard_header()` implementation**

Replace the full body of `render_student_wizard_header()` with:

```python
def render_student_wizard_header():
    """渲染聚焦式步骤条和当前步骤提示。"""
    current_step = st.session_state["student_current_step"]
    total_steps = len(STUDENT_STEP_TITLES)
    step_items = []
    for index, title in enumerate(STUDENT_STEP_TITLES, 1):
        if index < current_step:
            state_class = "done"
            status_text = "已完成"
            index_text = "✓"
        elif index == current_step:
            state_class = "active"
            status_text = "正在填写"
            index_text = str(index)
        else:
            state_class = ""
            status_text = "待填写"
            index_text = str(index)

        step_items.append(
            f"""
            <div class="pcr-stepper-item {state_class}">
                <div class="pcr-stepper-index">{index_text}</div>
                <div class="pcr-stepper-title">{title}</div>
                <div class="pcr-stepper-status">{status_text}</div>
            </div>
            """
        )

    with st.container(border=True):
        st.markdown(
            f"""
            <div class="pcr-current-step-summary">
                <div>
                    <div class="pcr-step-kicker">当前步骤</div>
                    <div class="pcr-step-title">第 {current_step} / {total_steps} 步：{STUDENT_STEP_TITLES[current_step - 1]}</div>
                    <div class="pcr-step-desc">聚焦完成当前输入；诊断会在最后一步统一生成并保存。</div>
                </div>
                <span class="pcr-current-step-chip">{round(current_step / total_steps * 100)}% 完成</span>
            </div>
            <div class="pcr-stepper-grid">
                {''.join(step_items)}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.progress(current_step / total_steps)
```

- [ ] **Step 4: Replace the large operation-step card in `main()`**

In `main()`, remove the whole block that starts with:

```python
    with st.container(border=True):
        render_card_title("操作步骤", "分步完成输入，再统一进入诊断结果区。")
```

and ends after the `st.button("加载演示数据", ...)` branch.

Then insert this call in its place:

```python
    render_student_quick_actions()
```

- [ ] **Step 5: Run syntax check for student page**

Run:

```powershell
python -m py_compile "pages/1_学生端.py"
```

Expected: command exits with code 0 and prints no syntax error.

- [ ] **Step 6: Commit compact stepper layout**

Run:

```powershell
git add "pages/1_学生端.py"
git commit -m "style: focus student workflow stepper"
```

Expected: commit succeeds and includes only `pages/1_学生端.py`.

---

### Task 3: Tighten Step Panels And Review Summary

**Files:**
- Modify: `D:\pcr_diagnosis\pages\1_学生端.py`

- [ ] **Step 1: Adjust step 1 title copy**

In `render_step_1_basic_info()`, keep the same fields and replace the title helper call with:

```python
        render_card_title("实验现象与对照情况", "先记录凝胶上看到的主要异常，再确认阳性/阴性对照表现。")
```

- [ ] **Step 2: Adjust step 2 title copy**

In `render_step_2_pcr_params()`, keep the same fields and replace the title helper call with:

```python
        render_card_title("PCR 关键参数", "填写会影响扩增结果的核心参数，用于匹配规则库。")
```

- [ ] **Step 3: Adjust step 3 layout**

In `render_step_3_text_and_image()`, replace the content inside `with st.container(border=True):` with:

```python
        render_card_title("补充描述与图片上传", "补充文字线索；凝胶图片可选上传，用于案例留存和教师复核。")
        desc_col, image_col = st.columns([0.58, 0.42])
        with desc_col:
            st.text_area(
                "学生补充描述",
                height=150,
                placeholder="请补充任何其他可能的信息，例如模板情况、体系怀疑点、异常观察等...",
                key="student_form_description",
                on_change=sync_val,
                args=("student_form_description",)
            )
        with image_col:
            uploaded_file = st.file_uploader(
                "上传凝胶图片（可选）",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=False,
                key="student_form_gel_image_file",
            )
            persist_uploaded_file(uploaded_file)

            image_bytes = st.session_state.get("student_uploaded_image_bytes")
            image_name = st.session_state.get("student_uploaded_image_name", "")
            if image_bytes:
                st.image(image_bytes, caption=f"当前暂存图片：{image_name}", use_container_width=True)
                if st.button("清除当前图片", key="student_clear_uploaded_image", use_container_width=True):
                    clear_student_uploaded_image()
                    st.rerun()
            else:
                st.info("当前未上传图片，也可以继续下一步。")
```

- [ ] **Step 4: Replace review summary bullets with review cards**

In `render_step_4_review()`, replace the content inside `with st.container(border=True):` with:

```python
        render_card_title("确认并开始诊断", "请核对输入摘要；确认无误后点击“开始诊断”。")
        image_status = "是" if form_data["gel_image_file"] else "否"
        description_text = form_data["description"] if form_data["description"] else "未填写"
        review_items = [
            ("实验现象", form_data["abnormality"]),
            ("阳性对照是否正常", form_data["positive_control_normal"]),
            ("阴性对照是否有带", form_data["negative_control_band"]),
            ("模板量", form_data["template_amount"]),
            ("退火温度", form_data["annealing_temp"]),
            ("循环数", form_data["cycles"]),
            ("是否已上传图片", image_status),
            ("学生补充描述", description_text),
        ]
        cards = []
        for label, value in review_items:
            cards.append(
                f"""
                <div class="pcr-review-item">
                    <div class="pcr-review-label">{label}</div>
                    <div class="pcr-review-value">{value}</div>
                </div>
                """
            )
        st.markdown(
            f"""
            <div class="pcr-review-grid">
                {''.join(cards)}
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("如需修改，可返回前面步骤继续调整；诊断结果会保存到教师端可查看的记录中。")
```

- [ ] **Step 5: Run syntax check**

Run:

```powershell
python -m py_compile "pages/1_学生端.py"
```

Expected: command exits with code 0 and prints no syntax error.

- [ ] **Step 6: Commit step panel polish**

Run:

```powershell
git add "pages/1_学生端.py"
git commit -m "style: polish student step panels"
```

Expected: commit succeeds and includes only `pages/1_学生端.py`.

---

### Task 4: Polish Result Metadata Layout

**Files:**
- Modify: `D:\pcr_diagnosis\pages\1_学生端.py`

- [ ] **Step 1: Replace result clue metadata markdown with compact cards**

In `render_student_results(payload)`, replace these two lines:

```python
        st.markdown(f"**文本线索来源：{clue_source}**")
        st.markdown(f"**抽取线索：{('、'.join(text_clues)) if text_clues else '未抽取到明显线索'}**")
```

with:

```python
        clue_text = "、".join(text_clues) if text_clues else "未抽取到明显线索"
        st.markdown(
            f"""
            <div class="pcr-result-meta-grid">
                <div class="pcr-review-item">
                    <div class="pcr-review-label">文本线索来源</div>
                    <div class="pcr-review-value">{clue_source}</div>
                </div>
                <div class="pcr-review-item">
                    <div class="pcr-review-label">抽取线索</div>
                    <div class="pcr-review-value">{clue_text}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
```

- [ ] **Step 2: Keep existing image and Top result behavior**

Inspect the rest of `render_student_results(payload)` and confirm these branches remain unchanged:

```python
        if image_save_error:
            st.warning(f"图片保存失败，但不影响诊断：{image_save_error}")
        if gel_image_path and os.path.exists(gel_image_path):
            st.image(gel_image_path, caption=f"已上传：{gel_image_path}", use_container_width=True)
        elif gel_image_path:
            st.info(f"图片已记录路径，但文件未找到：{gel_image_path}")
        else:
            st.info("本次未上传凝胶图片")
```

Expected: only the clue metadata display changes; image rendering, Top1 rendering, evidence expanders, and report export stay on the current paths.

- [ ] **Step 3: Run syntax check**

Run:

```powershell
python -m py_compile "pages/1_学生端.py"
```

Expected: command exits with code 0 and prints no syntax error.

- [ ] **Step 4: Commit result layout polish**

Run:

```powershell
git add "pages/1_学生端.py"
git commit -m "style: polish student result metadata"
```

Expected: commit succeeds and includes only `pages/1_学生端.py`.

---

### Task 5: End-To-End Verification

**Files:**
- Verify: `D:\pcr_diagnosis\core.py`
- Verify: `D:\pcr_diagnosis\pages\1_学生端.py`

- [ ] **Step 1: Run syntax checks for modified files**

Run:

```powershell
python -m py_compile core.py "pages/1_学生端.py"
```

Expected: command exits with code 0 and prints no syntax error.

- [ ] **Step 2: Start Streamlit**

Run:

```powershell
streamlit run app.py
```

Expected: Streamlit starts and prints a local URL such as `http://localhost:8501`.

- [ ] **Step 3: Manually verify student workflow**

In the browser, verify:

1. Open the student page.
2. Confirm the large "操作步骤" four-card block is gone.
3. Confirm the compact toolbar shows the demo-data action.
4. Click "加载演示数据".
5. Confirm step 1 is active in the stepper.
6. Click "下一步" through steps 2 and 3.
7. Confirm step 3 shows description and upload controls side-by-side on desktop.
8. Continue to step 4.
9. Confirm the review summary appears as compact cards.
10. Click "开始诊断".
11. Confirm Top1, Top2/Top3, evidence expanders, and report export still appear.

- [ ] **Step 4: Stop Streamlit**

Stop the Streamlit process with `Ctrl+C` in the terminal where it is running.

- [ ] **Step 5: Commit verification note if any code changed during verification**

If manual verification required code changes, commit those files with:

```powershell
git add core.py "pages/1_学生端.py"
git commit -m "fix: adjust student layout after verification"
```

Expected: commit succeeds only when verification required a code adjustment. If no code changed, skip this commit.

---

## Self-Review

- Spec coverage: The plan implements the confirmed focused wizard layout, compact stepper, lighter demo action, unchanged diagnosis flow, unchanged result behavior, and manual verification path.
- Placeholder scan: The plan contains no unresolved placeholders and each code-changing task includes exact snippets.
- Type consistency: All referenced functions already exist or are introduced in this plan; session keys and payload keys match the current student page.
