"""主动执行在线联调：只发送代码生成的图片和固定匿名文字，不读取学生数据。"""

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
import core
import ai_config
from followup_agent import interpret_operation_text, plan_followup_questions
from gel_image_assistant import prepare_image, request_observation


def main():
    if not ai_config.api_key():
        print("未检测到 DEEPSEEK_API_KEY；未执行在线调用。")
        return 1
    print("已检测到配置；固定模型 deepseek-flash；开始匿名文字与生成图片的接口联调。")
    hints, source = interpret_operation_text("核对配液记录，确认漏加了聚合酶。")
    print(f"操作线索接口：{source}；允许标签数量 {len(hints)}")
    _, wording_source = plan_followup_questions({"abnormality": "无条带", "positive_control_normal": "否"})
    print(f"追问接口：{wording_source}")
    _, extraction_source, debug = core.extract_text_clues_with_fallback("已确认模板浓度低。")
    print(f"文字抽取接口：{extraction_source}；未完成原因 {debug.get('fail_reason') or '无'}")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "generated-interface-check.png"
        image = Image.new("RGB", (640,400), (15,15,15))
        draw = ImageDraw.Draw(image)
        draw.rectangle((125,35,195,55), fill=(60,60,60))
        draw.rectangle((405,35,475,55), fill=(60,60,60))
        draw.rectangle((125,190,195,200), fill=(230,230,230))
        draw.rectangle((405,270,475,280), fill=(200,200,200))
        image.save(path)
        prepared = prepare_image(path,[{"lane_id":1,"role":"身份未确认"},{"lane_id":2,"role":"身份未确认"}])
        result = request_observation(prepared)
    print(f"图片接口：{result['status']}")
    if result["status"] != "success":
        print(result["error"])
        return 1
    print(f"图片响应模型：{result['model_returned']}；候选泳道数：{len(result['observations']['lanes'])}；Token：{result['usage']}")
    print("接口联调结束；没有写入课堂库，没有读取或发送学生照片；不代表真实电泳图准确率。")
    return 0 if source == "AI候选线索" and wording_source == "AI整理问法" and extraction_source == "AI（DeepSeek）抽取" else 1


if __name__ == "__main__":
    raise SystemExit(main())
