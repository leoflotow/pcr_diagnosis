"""集中打开、提交、上传的本机 HTTP 验证；仅可连接明确启动的隔离服务。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import statistics
import time
import uuid
from urllib.parse import urlparse
import requests
from PIL import Image


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8521');parser.add_argument('--qa-confirmed',action='store_true');args=parser.parse_args()
    if not args.qa_confirmed or urlparse(args.url).hostname not in {'127.0.0.1','localhost'}:
        raise SystemExit('必须先启动关闭真实配置读取的隔离服务，再明确传入 --qa-confirmed；禁止连接课堂环境。')
    image=BytesIO();Image.effect_noise((1600,1200),90).convert('RGB').save(image,'JPEG',quality=90);content=image.getvalue()
    def student(i):
        client=requests.Session();client.trust_env=False;client.headers['X-Teaching-Request']='1';times={}
        def measure(name,callback):
            start=time.perf_counter();response=callback();response.raise_for_status();times[name]=round(time.perf_counter()-start,4);return response
        measure('打开网页',lambda:client.get(args.url,timeout=30))
        measure('知识查询',lambda:client.get(args.url+'/api/v1/knowledge',params={'q':'pyruvate'},timeout=30))
        measure('建立会话',lambda:client.post(args.url+'/api/v1/session/guest',json={},timeout=30))
        created=measure('提交案例',lambda:client.post(args.url+'/api/v1/cases',json={'request_id':uuid.uuid4().hex,'abnormality':'无条带','student_initial_hypothesis':'需要核对对照，尚不能确认原因','group_code':f'QA-{i}'},timeout=30)).json()
        measure('上传图片',lambda:client.post(args.url+f"/api/v1/cases/{created['id']}/image",files={'file':('gel.jpg',content,'image/jpeg')},timeout=30))
        return times
    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=20) as pool:results=list(pool.map(student,range(20)))
    summary={k:{'中位秒':round(statistics.median(r[k] for r in results),4),'最大秒':max(r[k] for r in results)} for k in results[0]}
    output=Path(__file__).resolve().parents[1]/'build/qa/load.json';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'并发人数':20,'成功人数':len(results),'总耗时秒':round(time.perf_counter()-start,3),'生成图片字节':len(content),'阶段耗时':summary,'模型调用':0},ensure_ascii=False,indent=2),encoding='utf-8')
    print(output.read_text(encoding='utf-8'))


if __name__=='__main__':main()
