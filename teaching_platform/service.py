"""统一网页的业务适配层，复用已有规则与持久化，不依赖页面会话。"""
from io import BytesIO
from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from PIL import Image, ImageOps

import case_storage
import experiment_business as business
import teaching_workflow as workflow
from diagnosis_normalization import build_normalized_case, STANDARD_TEXT_HINTS
from diagnosis_rule_engine_v2 import evaluate_rules_v2
from followup_agent import _base_questions, apply_followup_choices
from evidence_support import parse_json
from .config import ROOT, brand


class Service:
    def __init__(self, db, uploads, knowledge):
        self.db=str(db);self.uploads=Path(uploads).resolve();self.knowledge=knowledge

    def initialize(self):
        path=Path(self.db);path.parent.mkdir(parents=True,exist_ok=True)
        if path.is_file():
            with closing(sqlite3.connect(path)) as source:
                known=source.execute("SELECT 1 FROM sqlite_master WHERE name='platform_task_links'").fetchone()
                backup=path.with_name(path.name+'.before-unified-platform.bak')
                if not known and not backup.exists():
                    with closing(sqlite3.connect(backup)) as target:source.backup(target)
        case_storage.init_database(self.db)
        with workflow.connection(self.db,True) as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS platform_task_links (
                    task_id INTEGER PRIMARY KEY, version INTEGER NOT NULL,
                    parent_task_id INTEGER, links_json TEXT NOT NULL, note TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS platform_evaluation_uploads (
                    id TEXT PRIMARY KEY, image_path TEXT NOT NULL);
            ''')
        self.uploads.mkdir(parents=True,exist_ok=True)

    def raw_record(self,rid):
        with workflow.connection(self.db) as conn:return workflow.classroom_record(conn,rid)

    def student(self,code,rid=None):
        digest=hashlib.sha256(str(code).strip().encode()).hexdigest()
        with workflow.connection(self.db) as conn:
            row=conn.execute('SELECT id FROM diagnosis_records WHERE student_access_hash=?',(digest,)).fetchone()
            if not row or rid is not None and row['id']!=rid:raise ValueError('查询码不正确或无权访问此案例。')
            return workflow.student_record(conn,row['id'],code)

    def diagnose(self,raw):
        hints=raw.get('confirmed_hints',[])
        if any(h not in STANDARD_TEXT_HINTS for h in hints):raise ValueError('事实线索无效。')
        normalized=build_normalized_case({**raw,'description':'','text_clues':hints,
            'positive_control_normal':raw.get('positive_control_detail') or raw.get('positive_control_normal','未观察'),
            'negative_control_band':raw.get('negative_control_detail') or raw.get('negative_control_band','未观察')})
        evaluated=evaluate_rules_v2(normalized,str(ROOT/'rules.csv'),str(ROOT/'rule_combos.csv'))
        diagnosis=business.build_primary_diagnosis_from_rules_v2(evaluated)
        return diagnosis, {'normalized_case':normalized,'text_clues':hints}

    def create_case(self,raw):
        code=secrets.token_urlsafe(18)
        diagnosis,evidence=self.diagnose(raw)
        raw={**raw,'data_origin':'真实课堂'}
        # 附件在事务内检查；失败不会产生无效案例。
        rid=case_storage.save_record(self.db,raw['abnormality'],raw.get('template_amount'),raw.get('annealing_temp'),raw.get('cycles'),
            raw.get('positive_control_normal','未观察'),raw.get('negative_control_band','未观察'),raw.get('description',''),
            diagnosis['result_text'],student_initial_hypothesis=raw['student_initial_hypothesis'],student_access_code=code,
            initial_results=diagnosis['results'],raw_case=raw,evidence=evidence)
        return {'id':rid,'query_code':code}

    def detail(self,rid,code=None,teacher=False):
        record=self.raw_record(rid) if teacher else self.student(code,rid)
        if teacher:workflow.mark_exposed(self.db,rid,True)
        clean={k:v for k,v in record.items() if k not in {'student_access_hash','gel_image_path'}}
        clean['has_image']=bool(record['gel_image_path'])
        clean['input']=parse_json(record.get('input_json'));clean['snapshot']=parse_json(record.get('diagnosis_snapshot_json'))
        clean['followup']=parse_json(record.get('followup_json'));clean['plan']=parse_json(record.get('verification_plan_json'))
        if 'final_results' in clean['followup']:clean['results']=clean['followup']['final_results']
        elif 'results' in clean['snapshot']:clean['results']=clean['snapshot']['results']
        else:clean['results']=business.build_ranked_results(candidate_texts=business.parse_all_candidates(record.get('diagnosis_result','')))
        clean['questions']=_base_questions(clean['followup'].get('updated_case') or clean['input'],clean['results'])
        clean['task_context']=workflow.record_task(self.db,rid,code,teacher)
        if clean['task_context']['task']:clean['task_context']['task']=self.task(clean['task_context']['task']['code'])
        clean['retests']=workflow.load_retests(self.db,rid,code,teacher)
        for item in clean['retests']:item['has_image']=bool(item.pop('image_path',None))
        clean['gel']=case_storage.load_gel_history(self.db,rid,code,teacher)
        with workflow.connection(self.db) as conn:
            clean['history']={
                'teacher':[dict(r) for r in conn.execute('SELECT * FROM teacher_review_history WHERE record_id=? ORDER BY review_version',(rid,))],
                'student':[dict(r) for r in conn.execute('SELECT * FROM student_revision_history WHERE record_id=? ORDER BY review_version',(rid,))],
                'evaluations':[dict(r) for r in conn.execute('SELECT * FROM learning_evaluations WHERE record_id=? ORDER BY id',(rid,))]}
        return clean

    def task(self,code):
        task=workflow.task_by_code(self.db,code)
        if not task:raise ValueError('课堂任务不存在，请核对任务码。')
        with workflow.connection(self.db) as conn:link=conn.execute('SELECT * FROM platform_task_links WHERE task_id=?',(task['id'],)).fetchone()
        task.update(knowledge=parse_json(link['links_json']) if link else {'items':[]},
                    knowledge_note=link['note'] if link else '',version=link['version'] if link else 1,
                    status=workflow.task_status(task))
        return task

    def create_task(self,payload):
        ids=payload.get('knowledge_ids',[])
        if not isinstance(ids,list) or any(not isinstance(i,str) or i not in self.knowledge.entities for i in ids):raise ValueError('关联词条不存在，请重新查询。')
        snap=self.knowledge.snapshot(ids)
        parent=payload.get('parent_task_id');version=1
        if parent:
            with workflow.connection(self.db) as conn:
                old=conn.execute('SELECT t.code FROM teaching_tasks t WHERE t.id=?',(parent,)).fetchone()
            if not old:raise ValueError('待修订任务不存在。')
            version=self.task(old['code'])['version']+1
        def freeze_links(conn,tid):
            conn.execute('INSERT INTO platform_task_links VALUES (?,?,?,?,?)',(tid,version,parent,json.dumps(snap,ensure_ascii=False),workflow.text(payload.get('knowledge_note'),'知识阅读提示',2000,False)))
            if parent and not payload.get('scheme_id'):
                conn.execute('UPDATE teaching_tasks SET scheme_json=(SELECT scheme_json FROM teaching_tasks WHERE id=?) WHERE id=?',(parent,tid))
        code=workflow.create_task(self.db,payload.get('title'),payload.get('instructions'),payload.get('transfer_prompt',''),
            payload.get('due_at',''),payload.get('scheme_id'),True,freeze_links)
        return self.task(code)

    def image_path(self,path):
        candidate=Path(path or '')
        if not candidate.is_absolute():candidate=ROOT/candidate
        candidate=candidate.resolve()
        if not candidate.is_relative_to(self.uploads) or not candidate.is_file():raise ValueError('图片不存在或不在允许的保存目录。')
        return candidate

    def upload(self,content):
        if not 0<len(content)<=10*1024*1024:raise ValueError('请使用不超过10 MB的PNG或JPG图片。')
        try:
            with Image.open(BytesIO(content)) as image:
                if image.format not in {'PNG','JPEG'} or image.width*image.height>40_000_000:raise ValueError('图片格式或尺寸无效。')
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image=ImageOps.exif_transpose(image).convert('RGB');image.info.clear()
                target=self.uploads/(secrets.token_hex(16)+'.png');image.save(target,format='PNG')
                return str(target)
        except (OSError,Image.DecompressionBombError) as exc:raise ValueError('图片无法读取，请重新导出PNG或JPG。') from exc

    def case_image(self,rid,content,code):
        self.student(code,rid)
        path=self.upload(content)
        try:
            with workflow.connection(self.db,True) as conn:
                record=workflow.student_record(conn,rid,code)
                if record['gel_image_path']:raise ValueError('原图已保存，不覆盖；新实验图片请通过实际复测追加。')
                conn.execute('UPDATE diagnosis_records SET gel_image_path=? WHERE id=?',(path,rid))
        except Exception:
            Path(path).unlink(missing_ok=True);raise

    def followup(self,rid,code,payload):
        record=self.student(code,rid)
        raw=parse_json(record['input_json']);previous=parse_json(record['followup_json'])
        updated=apply_followup_choices(previous.get('updated_case') or raw,payload.get('answers',{}))
        hints=list(dict.fromkeys(raw.get('confirmed_hints',[])+previous.get('extra_hints',[])+payload.get('hints',[])))
        updated['confirmed_hints']=hints
        result,evidence=self.diagnose(updated)
        data={'initial_results':parse_json(record['diagnosis_snapshot_json']).get('results',[]),'final_results':result['results'],
              'updated_case':updated,'answers':payload.get('answers',{}),'extra_hints':hints,'evidence':evidence,
              'operation_text':workflow.text(payload.get('operation'),'补充操作记录',2000,False)}
        if not case_storage.save_reassessment(self.db,rid,result['result_text'],updated.get('positive_control_normal'),updated.get('negative_control_band'),data):
            raise ValueError('教师已复核，不能覆盖补证结果；请刷新查看反馈。')

    def report(self,rid):
        report=business.build_case_review_report({'record_id':rid},self.db)
        identity=brand();lines=report.splitlines()
        if len(lines)>1:lines[:2]=[f"《{identity['name']} · 实验复盘报告》",identity['subtitle']]
        return '\n'.join(lines)
