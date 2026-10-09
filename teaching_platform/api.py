"""同源网页接口；所有身份验证由后台执行，不信任客户端授权字段。"""
from contextlib import asynccontextmanager
from io import BytesIO
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlparse

from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Depends, Query
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat

import ai_config
import case_storage
import teaching_workflow as w
import gel_image_assistant as gel
from diagnosis_normalization import STANDARD_TEXT_HINTS
from evidence_support import parse_json
from .config import ROOT, setting, brand, initialize_environment
from .knowledge import Knowledge
from .service import Service


class Credentials(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code: str=Field(min_length=1,max_length=200)
    role: str='student'


class CaseInput(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    request_id: str=Field(min_length=16,max_length=80)
    abnormality: str=Field(min_length=1,max_length=80)
    description: str=Field(default='',max_length=5000)
    student_initial_hypothesis: str=Field(min_length=1,max_length=5000)
    positive_control_normal: str='未观察'
    negative_control_band: str='未观察'
    positive_control_detail: str=''
    negative_control_detail: str=''
    band_pattern: str=''
    confirmed_hints: list[str]=Field(default_factory=list,max_length=30)
    course_name: str=Field(default='',max_length=120)
    class_name: str=Field(default='',max_length=120)
    group_code: str=Field(default='',max_length=120)
    experiment_name: str=Field(default='PCR 与电泳实验',max_length=120)
    teaching_task_code: str=Field(default='',max_length=30)
    template_amount: PositiveFloat | None=None
    template_concentration: PositiveFloat | None=None
    reaction_volume: PositiveFloat | None=None
    annealing_temp: PositiveFloat | None=None
    recommended_temp: PositiveFloat | None=None
    target_size: PositiveFloat | None=None
    cycles: int | None=Field(default=None,gt=0,le=100)
    template_type: str=Field(default='待确认',max_length=50)
    polymerase: str=Field(default='',max_length=120)
    gel_notes: str=Field(default='',max_length=2000)


def create_app(db_path=None,upload_dir=None,knowledge_path=None):
    os.environ['BIO_WEB_MODE']='1'
    initialize_environment()
    knowledge=Knowledge(knowledge_path)
    service=Service(db_path or setting('PCR_DIAGNOSIS_DB_PATH',str(ROOT/'data/app.db')),
                    upload_dir or setting('PCR_DIAGNOSIS_UPLOAD_DIR',str(ROOT/'uploads')),knowledge)
    sessions={};gate=threading.RLock();attempts={};observation_locks={}

    @asynccontextmanager
    async def lifespan(app):
        service.initialize();yield
        sessions.clear()

    app=FastAPI(title='生物实验教学平台',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.service=service

    @app.exception_handler(ValueError)
    async def value_error(request,exc):return JSONResponse({'detail':str(exc)},status_code=400)

    @app.exception_handler(sqlite3.OperationalError)
    async def db_error(request,exc):return JSONResponse({'detail':'保存暂未完成，请稍后重试；不会清理已有记录。'},status_code=503)

    @app.middleware('http')
    async def protect(request,call_next):
        if request.method not in {'GET','HEAD','OPTIONS'}:
            if request.headers.get('x-teaching-request')!='1':return JSONResponse({'detail':'请求来源无效，请从系统页面操作。'},403)
            origin=request.headers.get('origin')
            if origin and urlparse(origin).netloc!=request.headers.get('host'):return JSONResponse({'detail':'不允许跨站写入。'},403)
            try:length=int(request.headers.get('content-length','0'))
            except ValueError:return JSONResponse({'detail':'请求长度无效。'},400)
            if length>12*1024*1024:return JSONResponse({'detail':'上传内容过大。'},413)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
        return response

    def session(request:Request):
        token=request.cookies.get('bio_session','');digest=hashlib.sha256(token.encode()).hexdigest()
        with gate:
            state=sessions.get(digest)
            if not state or state['expires']<time.time():
                sessions.pop(digest,None)
                raise HTTPException(401,'请重新验证访问码或查询码。')
            return state

    def teacher(state=Depends(session)):
        if state['role']!='teacher':raise HTTPException(403,'此操作需要教师权限。')
        return state

    def student(rid,state):
        code=state['codes'].get(rid)
        if not code:raise HTTPException(403,'请先用对应的私有查询码找回案例。')
        service.student(code,rid);return code

    def authorize(rid,state):
        if state['role']=='teacher':service.raw_record(rid);return None
        return student(rid,state)

    def result(ok):
        if not ok:raise HTTPException(409,'记录已变化、内容不完整或本阶段已提交，请刷新核对。')
        return {'ok':True}

    @app.get('/api/v1/health')
    def health():return {'status':'ok','service':'biology-teaching-platform'}

    @app.get('/api/v1/config')
    def config():
        return {'brand':brand(),'hints':STANDARD_TEXT_HINTS,'roles':gel.ROLES,'patterns':gel.PATTERNS,
                'positions':gel.POSITIONS,'brightness':gel.BRIGHTNESS,'qualities':gel.QUALITIES,
                'quality_issues':gel.ISSUES,'check_states':gel.CHECK_STATES,'dimensions':w.DIMENSIONS,
                'retest_fields':w.RETEST_FIELDS,'scheme_fields':w.SCHEME_FIELDS,'scheme_numbers':list(w.SCHEME_NUMBERS),
                'presets':json.loads((ROOT/'course_presets.json').read_text(encoding='utf-8-sig')),
                'knowledge_version':knowledge.version,'vision_available':bool(ai_config.api_key()) and ai_config.vision_enabled()}

    @app.post('/api/v1/session')
    def login(body:Credentials,request:Request):
        peer=request.client.host if request.client else 'local'
        with gate:
            times=[t for t in attempts.get(peer,[]) if t>time.time()-60]
            if len(times)>=15:raise HTTPException(429,'尝试次数较多，请一分钟后再试。')
            attempts[peer]=times+[time.time()]
        if body.role=='teacher':
            expected=setting('TEACHER_ACCESS_CODE')
            if not expected or not hmac.compare_digest(body.code,expected):raise HTTPException(401,'教师访问码不正确或尚未配置。')
            codes={}
        elif body.role=='student':
            record=service.student(body.code);codes={record['id']:body.code}
        else:raise HTTPException(400,'访问身份无效。')
        token=secrets.token_urlsafe(32)
        with gate:
            expired=[k for k,v in sessions.items() if v['expires']<time.time()]
            for k in expired:sessions.pop(k,None)
            sessions[hashlib.sha256(token.encode()).hexdigest()]={'role':body.role,'codes':codes,'expires':time.time()+8*3600,'requests':{}}
        response=JSONResponse({'role':body.role,'case_id':next(iter(codes),None)})
        response.set_cookie('bio_session',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=8*3600)
        return response

    @app.post('/api/v1/session/guest')
    def guest(request:Request):
        # 提交前先建立会话，响应丢失后重试仍可使用相同提交编号。
        with gate:
            digest=hashlib.sha256(request.cookies.get('bio_session','').encode()).hexdigest()
            existing=sessions.get(digest)
            if existing and existing['expires']>time.time():return {'ok':True}
            token=secrets.token_urlsafe(32)
            sessions[hashlib.sha256(token.encode()).hexdigest()]={'role':'student','codes':{},'expires':time.time()+8*3600,'requests':{}}
        response=JSONResponse({'ok':True})
        response.set_cookie('bio_session',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=8*3600)
        return response

    @app.get('/api/v1/session')
    def current(state=Depends(session)):return {'role':state['role'],'case_ids':list(state['codes'])}

    @app.post('/api/v1/logout')
    def logout(request:Request):
        with gate:sessions.pop(hashlib.sha256(request.cookies.get('bio_session','').encode()).hexdigest(),None)
        response=JSONResponse({'ok':True});response.delete_cookie('bio_session');return response

    @app.get('/api/v1/knowledge')
    def search(q:str=Query('',max_length=200),kind:str='',offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100)):
        return knowledge.search(q,kind,offset,limit)

    @app.get('/api/v1/knowledge/{uid}')
    def entry(uid:str):return knowledge.detail(uid)

    @app.post('/api/v1/knowledge/resolve')
    def resolve(body:dict):
        ids=body.get('ids',[])
        if not isinstance(ids,list) or len(ids)>500:raise ValueError('收藏文件最多500项。')
        mapped=[knowledge.legacy.get(uid,uid) for uid in ids if isinstance(uid,str)]
        return {'items':[knowledge.summary(knowledge.entities[i]) for i in dict.fromkeys(mapped) if i in knowledge.entities],
                'missing':[i for i in mapped if i not in knowledge.entities],'version':knowledge.version}

    @app.get('/api/v1/tasks/{code}')
    def task(code:str):return service.task(code)

    @app.post('/api/v1/cases')
    def create_case(body:CaseInput,request:Request):
        from fastapi.responses import JSONResponse
        raw=body.model_dump(exclude={'request_id'})
        symptoms={'无条带','条带弱','多条带或非特异扩增','条带大小不对','条带拖尾或弥散','阴性对照有带','阳性对照无带','条带畸形'}
        if raw['abnormality'] not in symptoms or not raw['student_initial_hypothesis'].strip():raise ValueError('请完整填写实验现象与独立初判。')
        with gate:
            token=request.cookies.get('bio_session','');digest=hashlib.sha256(token.encode()).hexdigest()
            state=sessions.get(digest)
            fresh=not state or state['expires']<time.time()
            if fresh:
                token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest()
                state={'role':'student','codes':{},'expires':time.time()+8*3600,'requests':{}};sessions[digest]=state
            if state['role']=='teacher':raise ValueError('请退出教师身份后提交学生案例。')
            payload_hash=hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            cached=state['requests'].get(body.request_id)
            if cached:
                if cached['hash']!=payload_hash:raise HTTPException(409,'提交编号已使用，修改内容后请重新发起提交。')
                created=cached['result']
            else:
                created=service.create_case(raw);state['codes'][created['id']]=created['query_code']
                state['requests'][body.request_id]={'hash':payload_hash,'result':created}
        response=JSONResponse(created)
        if fresh:response.set_cookie('bio_session',token,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=8*3600)
        return response

    @app.get('/api/v1/cases/{rid}')
    def detail(rid:int,state=Depends(session)):
        code=authorize(rid,state);return service.detail(rid,code,state['role']=='teacher')

    @app.post('/api/v1/cases/{rid}/image')
    def upload_case(rid:int,file:UploadFile=File(...),state=Depends(session)):
        service.case_image(rid,file.file.read(10*1024*1024+1),student(rid,state));return {'ok':True}

    @app.get('/api/v1/cases/{rid}/image')
    def case_image(rid:int,state=Depends(session)):
        authorize(rid,state);return FileResponse(service.image_path(service.raw_record(rid)['gel_image_path']),media_type='image/png')

    @app.get('/api/v1/cases/{rid}/retests/{retest_id}/image')
    def retest_image(rid:int,retest_id:int,state=Depends(session)):
        authorize(rid,state)
        with w.connection(service.db) as conn:row=conn.execute('SELECT image_path FROM experiment_retests WHERE id=? AND record_id=?',(retest_id,rid)).fetchone()
        if not row:raise ValueError('复测记录不存在。')
        return FileResponse(service.image_path(row['image_path']))

    @app.get('/api/v1/cases/{rid}/report')
    def report(rid:int,state=Depends(session)):
        authorize(rid,state)
        if state['role']=='teacher':w.mark_exposed(service.db,rid,True)
        return Response(service.report(rid),media_type='text/plain; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="case-{rid}.txt"'})

    @app.post('/api/v1/cases/{rid}/followup')
    def followup(rid:int,body:dict,state=Depends(session)):
        with gate:service.followup(rid,student(rid,state),body)
        return {'ok':True}

    @app.post('/api/v1/cases/{rid}/clues')
    def clues(rid:int,body:dict,state=Depends(session)):
        student(rid,state)
        from followup_agent import interpret_operation_text
        candidates,source=interpret_operation_text(w.text(body.get('text'),'操作记录',2000))
        return {'candidates':candidates,'source':source}

    @app.post('/api/v1/cases/{rid}/revision')
    def revision(rid:int,body:dict,state=Depends(session)):
        code=student(rid,state)
        if type(body.get('version')) is not int:raise ValueError('缺少教师反馈版本，请刷新。')
        return result(case_storage.save_revision(service.db,rid,code,w.text(body.get('cause'),'修订原因',500),w.text(body.get('reason'),'修订依据'),body['version']))

    @app.post('/api/v1/cases/{rid}/plan')
    def plan(rid:int,body:dict,state=Depends(session)):
        return result(case_storage.save_verification_plan(service.db,rid,student(rid,state),body))

    @app.post('/api/v1/cases/{rid}/transfer')
    def transfer(rid:int,body:dict,state=Depends(session)):
        w.save_transfer(service.db,rid,student(rid,state),body.get('answer'),body.get('reasoning'),body.get('minutes'));return {'ok':True}

    @app.post('/api/v1/cases/{rid}/retest')
    def retest(rid:int,body:dict,state=Depends(session)):
        return {'id':w.save_retest(service.db,rid,student(rid,state),body)}

    @app.post('/api/v1/cases/{rid}/retests/{retest_id}/image')
    def retest_upload(rid:int,retest_id:int,file:UploadFile=File(...),state=Depends(session)):
        student(rid,state);path=service.upload(file.file.read(10*1024*1024+1))
        try:
            with w.connection(service.db,True) as conn:
                row=conn.execute('SELECT * FROM experiment_retests WHERE id=? AND record_id=?',(retest_id,rid)).fetchone()
                reviewed=conn.execute('SELECT 1 FROM retest_reviews WHERE retest_id=?',(retest_id,)).fetchone()
                if not row or row['image_path'] or reviewed:raise ValueError('复测不存在、已保存原图或已经复核，不能覆盖。')
                conn.execute('UPDATE experiment_retests SET image_path=?,image_sha=? WHERE id=?',(path,hashlib.sha256(Path(path).read_bytes()).hexdigest(),retest_id))
        except Exception:Path(path).unlink(missing_ok=True);raise
        return {'ok':True}

    @app.post('/api/v1/cases/{rid}/gel/preview')
    def preview(rid:int,body:dict,state=Depends(session)):
        authorize(rid,state);record=service.raw_record(rid)
        prepared=gel.prepare_image(service.image_path(record['gel_image_path']),body.get('mapping'),body.get('settings'))
        import base64
        return {k:v for k,v in prepared.items() if k!='image_bytes'} | {'preview':'data:image/png;base64,'+base64.b64encode(prepared['image_bytes']).decode()}

    @app.post('/api/v1/cases/{rid}/gel/observe')
    def observe(rid:int,body:dict,state=Depends(session)):
        code=student(rid,state)
        if body.get('consent') is not True:raise ValueError('请先确认发送区域与匿名泳道身份。')
        record=service.raw_record(rid)
        prepared=gel.prepare_image(service.image_path(record['gel_image_path']),body.get('mapping'),body.get('settings'))
        if body.get('context_key')!=prepared['context_key']:raise ValueError('发送区域已变化，请重新预览确认。')
        with gate:
            observation_lock=observation_locks.setdefault((rid,prepared['context_key']),threading.Lock())
        with observation_lock:
            history=case_storage.load_gel_history(service.db,rid,code)
            match=next((r for r in history['runs'] if r['context_key']==prepared['context_key'] and r['status']=='success'),None)
            if match and not body.get('force'):return {'status':'success','id':match['id'],'reused':True}
            response=gel.request_observation(prepared)
            if response['status'] in {'success','failed'}:response['id']=case_storage.save_gel_run(service.db,rid,code,prepared,response)
        return response

    @app.post('/api/v1/cases/{rid}/gel/check')
    def check(rid:int,body:dict,state=Depends(session)):
        teacher_mode=state['role']=='teacher';code=authorize(rid,state)
        return {'id':case_storage.save_gel_check(service.db,rid,body.get('run_id'),body.get('context_key'),body.get('entries'),
             'teacher' if teacher_mode else 'student',code,teacher_mode,body.get('source_student_check_id'))}

    @app.get('/api/v1/teacher/cases')
    def cases(state=Depends(teacher)):
        with w.connection(service.db) as conn:
            return [dict(r) for r in conn.execute("SELECT id,abnormality,diagnosis_time,course_name,class_name,group_code,data_origin,teacher_review_version FROM diagnosis_records WHERE COALESCE(data_origin,'') NOT IN ('模拟演示','规则回归') ORDER BY id DESC")]

    @app.get('/api/v1/teacher/cases/{rid}/independent')
    def independent(rid:int,state=Depends(teacher)):
        item=w.independent_record(service.db,rid,True)
        item['raw']['has_image']=bool(item['raw'].pop('gel_image_path',None))
        # 已存独立判断的内部快照不能提前泄露系统候选。
        if item['review']:item['review'].pop('snapshot_json',None)
        return item

    @app.post('/api/v1/teacher/cases/{rid}/independent')
    def save_independent(rid:int,body:dict,state=Depends(teacher)):
        w.save_independent_review(service.db,rid,body.get('cause'),body.get('reason'),body.get('evidence_level'),True);return {'ok':True}

    @app.post('/api/v1/teacher/cases/{rid}/review')
    def review(rid:int,body:dict,state=Depends(teacher)):
        service.raw_record(rid)
        if type(body.get('version')) is not int:raise ValueError('缺少反馈版本，请刷新。')
        if body.get('evidence_level') not in {'经验复核','原始记录支持','复测验证','原因待核实'}:raise ValueError('证据等级无效。')
        w.mark_exposed(service.db,rid,True)
        return result(case_storage.save_review(service.db,rid,w.text(body.get('cause'),'原因',500),w.text(body.get('note'),'依据',required=False),
            body['evidence_level'],w.text(body.get('verification_feedback'),'验证计划反馈',required=False),body['version'],body.get('rubric'),body.get('data_origin')))

    @app.post('/api/v1/teacher/cases/{rid}/evaluate')
    def evaluate(rid:int,body:dict,state=Depends(teacher)):
        w.save_learning_evaluation(service.db,rid,body.get('stage'),body.get('rubric',{}),body.get('note',''),True);return {'ok':True}

    @app.post('/api/v1/teacher/retests/{retest_id}/review')
    def retest_review(retest_id:int,body:dict,state=Depends(teacher)):
        w.review_retest(service.db,retest_id,body.get('conclusion'),body.get('note'),body.get('expected_review_id'),True);return {'ok':True}

    @app.get('/api/v1/teacher/tasks')
    def tasks(state=Depends(teacher)):return [service.task(t['code']) for t in w.list_tasks(service.db,True)]

    @app.post('/api/v1/teacher/tasks')
    def create_task(body:dict,state=Depends(teacher)):
        with gate:return service.create_task(body)

    @app.post('/api/v1/teacher/tasks/{tid}/status')
    def task_status(tid:int,body:dict,state=Depends(teacher)):
        if type(body.get('active')) is not bool:raise ValueError('任务状态无效。')
        w.set_task_active(service.db,tid,body['active'],True);return {'ok':True}

    @app.get('/api/v1/teacher/tasks/{tid}/export')
    def task_export(tid:int,state=Depends(teacher)):
        import csv
        from io import StringIO
        rows=w.task_export(service.db,tid,True);text=StringIO();writer=csv.DictWriter(text,fieldnames=list(rows[0]) if rows else ['案例编号']);writer.writeheader();writer.writerows(rows)
        return Response('\ufeff'+text.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="task-{tid}.csv"'})

    @app.get('/api/v1/schemes')
    def schemes():return w.list_schemes(service.db)

    @app.post('/api/v1/teacher/schemes')
    def scheme(body:dict,state=Depends(teacher)):
        return {'id':w.save_scheme(service.db,body.get('name'),body.get('payload',{}),body.get('source'),body.get('expected_version',0),True)}

    @app.get('/api/v1/teacher/issues')
    def issues(task_id:int|None=None,state=Depends(teacher)):
        context=w.build_issues(service.db,task_id,True)
        return {'context':context,'latest':w.latest_suggestions(service.db,context,True),'actions':w.ISSUE_ACTIONS}

    @app.post('/api/v1/teacher/issues/suggest')
    def suggest(body:dict,state=Depends(teacher)):
        context=w.build_issues(service.db,body.get('task_id'),True)
        response=w.request_teaching_suggestions(context);w.save_suggestions(service.db,context,response,True);return response

    @app.post('/api/v1/teacher/evaluations/image')
    def evaluation_upload(file:UploadFile=File(...),state=Depends(teacher)):
        path=service.upload(file.file.read(10*1024*1024+1));uid=secrets.token_hex(16)
        with w.connection(service.db,True) as conn:conn.execute('INSERT INTO platform_evaluation_uploads VALUES (?,?)',(uid,path))
        return {'upload_id':uid}

    def evaluation_image(uid):
        with w.connection(service.db) as conn:row=conn.execute('SELECT image_path FROM platform_evaluation_uploads WHERE id=?',(uid,)).fetchone()
        if not row:raise ValueError('图片不存在，请重新上传。')
        return service.image_path(row['image_path'])

    @app.get('/api/v1/teacher/evaluations/uploads/{uid}')
    def show_evaluation_upload(uid:str,state=Depends(teacher)):return FileResponse(evaluation_image(uid))

    @app.post('/api/v1/teacher/evaluations/preview')
    def evaluation_preview(body:dict,state=Depends(teacher)):
        import base64
        prepared=gel.prepare_image(evaluation_image(body.get('upload_id')),body.get('mapping'),body.get('settings'))
        return {'preview':'data:image/png;base64,'+base64.b64encode(prepared['image_bytes']).decode(),'context_key':prepared['context_key']}

    @app.post('/api/v1/teacher/evaluations')
    def save_sample(body:dict,state=Depends(teacher)):
        if body.get('independent_consent') is not True:raise ValueError('请确认已获准使用图片并独立标注。')
        path=evaluation_image(body.get('upload_id'));prepared=gel.prepare_image(path,body.get('mapping'),body.get('settings'))
        if body.get('context_key')!=prepared['context_key']:raise ValueError('请重新预览参考区域。')
        return {'id':w.save_evaluation_sample(service.db,path,prepared,body.get('reference'),body.get('disputed',[]),body.get('family'),body.get('split'),body.get('quality'),True)}

    @app.get('/api/v1/teacher/evaluations')
    def samples(state=Depends(teacher)):
        samples=w.evaluation_samples(service.db,True);runs=w.evaluation_runs(service.db,teacher_authorized=True)
        for sample in samples:
            sample.pop('image_path',None);sample['runs']=[r for r in runs if r['sample_id']==sample['id']]
            sample['comparisons']=[c for r in sample['runs'] for c in w.evaluation_comparison(sample,r)]
        return samples

    @app.get('/api/v1/teacher/evaluations/{sid}/image')
    def sample_image(sid:int,state=Depends(teacher)):
        sample=next((s for s in w.evaluation_samples(service.db,True) if s['id']==sid),None)
        if not sample:raise ValueError('参考样本不存在。')
        return FileResponse(service.image_path(sample['image_path']))

    @app.get('/api/v1/teacher/evaluations/{sid}/preview')
    def sample_preview(sid:int,state=Depends(teacher)):
        sample=next((s for s in w.evaluation_samples(service.db,True) if s['id']==sid),None)
        if not sample:raise ValueError('参考样本不存在。')
        return Response(w.prepare_evaluation(sample)['image_bytes'],media_type='image/png')

    @app.post('/api/v1/teacher/evaluations/{sid}/observe')
    def evaluation_observe(sid:int,body:dict,state=Depends(teacher)):
        if body.get('consent') is not True:raise ValueError('请确认发送已保存参考标注对应的区域。')
        sample=next((s for s in w.evaluation_samples(service.db,True) if s['id']==sid),None)
        if not sample:raise ValueError('参考样本不存在。')
        prepared=w.prepare_evaluation(sample);response=gel.request_observation(prepared)
        if response['status'] in {'success','failed'}:response['id']=w.save_evaluation_run(service.db,sid,prepared,response,True)
        return response

    @app.post('/api/v1/teacher/evaluations/runs/{run_id}/audit')
    def audit(run_id:int,body:dict,state=Depends(teacher)):
        w.save_evaluation_audit(service.db,run_id,body.get('mismatches',[]),body.get('note',''),True);return {'ok':True}

    assets=ROOT/'frontend/dist'
    if (assets/'assets').is_dir():app.mount('/assets',StaticFiles(directory=assets/'assets'),name='assets')

    @app.get('/{page:path}')
    def frontend(page:str):
        if page.startswith('api/'):raise HTTPException(404,'接口不存在。')
        if not (assets/'index.html').is_file():raise HTTPException(503,'统一网页尚未构建，请运行网页构建步骤。')
        return FileResponse(assets/'index.html',headers={'Cache-Control':'no-cache'})

    return app

