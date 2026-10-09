"""隔离库检验新网页与旧业务一致性、权限及知识更新；不读取课堂配置。"""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import copy
import json
import os
import sqlite3
import shutil
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient

from teaching_platform.api import create_app
from teaching_platform.knowledge import Knowledge
from scripts.build_knowledge import build
from diagnosis_normalization import build_normalized_case
from diagnosis_rule_engine_v2 import evaluate_rules_v2
import experiment_business as business
import case_storage
import teaching_workflow as w


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'BIO_CONFIG_DISABLED':'1','PYTHON_DOTENV_DISABLED':'1','DEEPSEEK_API_KEY':'','TEACHER_ACCESS_CODE':'test-teacher'});self.env.start()
        self.app=create_app(self.root/'app.db',self.root/'images')
        self.client=TestClient(self.app);self.client.__enter__();self.client.headers['X-Teaching-Request']='1'
        self.service=self.app.state.service

    def tearDown(self):
        self.client.__exit__(None,None,None);self.env.stop();self.temp.cleanup()

    def create(self,client=None,**kwargs):
        payload={'request_id':'request-'+'a'*24,'abnormality':'无条带','student_initial_hypothesis':'先检查模板与对照','description':'可能污染，尚未核实',**kwargs}
        response=(client or self.client).post('/api/v1/cases',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        return response.json(),payload

    def teacher(self):
        client=TestClient(self.app);client.headers['X-Teaching-Request']='1'
        r=client.post('/api/v1/session',json={'role':'teacher','code':'test-teacher'});self.assertEqual(r.status_code,200)
        return client

    def png(self):
        stream=BytesIO();Image.new('RGB',(160,100),'black').save(stream,'PNG');return stream.getvalue()

    def test_backend_import_does_not_depend_on_streamlit(self):
        import ast
        for file in ['experiment_business.py','teaching_platform/api.py','teaching_platform/service.py']:
            source=Path(file).read_text(encoding='utf-8');tree=ast.parse(source)
            self.assertFalse(any(isinstance(n,ast.Import) and any(a.name=='streamlit' for a in n.names) for n in ast.walk(tree)))

    def test_rules_equivalent_and_unconfirmed_description_excluded(self):
        created,payload=self.create()
        record=self.client.get(f"/api/v1/cases/{created['id']}").json()
        normalized=build_normalized_case({'abnormality':'无条带','description':'','text_clues':[],'positive_control_normal':'未观察','negative_control_band':'未观察'})
        expected=business.build_primary_diagnosis_from_rules_v2(evaluate_rules_v2(normalized))
        self.assertEqual(record['results'],expected['results'])
        self.assertEqual(record['snapshot']['evidence']['text_clues'],[])
        self.assertNotIn('student_access_hash',record);self.assertNotIn('gel_image_path',record)

    def test_empty_followup_does_not_restore_old_candidates(self):
        created,_=self.create();rid=created['id']
        with w.connection(self.service.db,True) as conn:
            conn.execute('UPDATE diagnosis_records SET diagnosis_snapshot_json=?,followup_json=? WHERE id=?',(json.dumps({'results':[{'原因':'旧候选'}]}),json.dumps({'final_results':[]}),rid))
        self.assertEqual(self.client.get(f'/api/v1/cases/{rid}').json()['results'],[])


    def test_submission_retry_has_one_record_and_changed_payload_rejected(self):
        created,payload=self.create()
        again=self.client.post('/api/v1/cases',json=payload)
        self.assertEqual(again.json(),created)
        with w.connection(self.service.db) as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM diagnosis_records').fetchone()[0],1)
        self.assertEqual(self.client.post('/api/v1/cases',json={**payload,'description':'修改后'}).status_code,409)

    def test_private_code_permissions_and_cross_site_writes(self):
        created,payload=self.create();rid=created['id']
        outsider=TestClient(self.app)
        self.assertEqual(outsider.get(f'/api/v1/cases/{rid}').status_code,401)
        self.assertEqual(outsider.get(f'/api/v1/cases/{rid}/image').status_code,401)
        self.assertEqual(outsider.get(f'/api/v1/cases/{rid}/report').status_code,401)
        self.assertEqual(outsider.post('/api/v1/cases',json=payload).status_code,403)
        self.assertEqual(self.client.post('/api/v1/cases',json=payload,headers={'Origin':'https://elsewhere.invalid'}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/teacher/tasks',json={'title':'unauthorized'}).status_code,403)

    def test_independent_review_does_not_leak_candidates_and_exposure_is_enforced(self):
        created,_=self.create();rid=created['id'];teacher=self.teacher()
        blind=teacher.get(f'/api/v1/teacher/cases/{rid}/independent').json()
        self.assertTrue(blind['eligible']);self.assertNotIn('snapshot',blind);self.assertNotIn('diagnosis_result',blind['raw'])
        teacher.get(f'/api/v1/cases/{rid}')
        response=teacher.post(f'/api/v1/teacher/cases/{rid}/independent',json={'cause':'模板不足','reason':'待核对浓度','evidence_level':'原因待核实'})
        self.assertEqual(response.status_code,400)

    def test_stale_revision_rejected_and_history_never_recomputes(self):
        created,_=self.create();rid=created['id'];teacher=self.teacher()
        review={'cause':'待核实','note':'补充对照','version':0,'evidence_level':'原因待核实'}
        self.assertEqual(teacher.post(f'/api/v1/teacher/cases/{rid}/review',json=review).status_code,200)
        stale=self.client.post(f'/api/v1/cases/{rid}/revision',json={'version':0,'cause':'待核实','reason':'先核对'})
        self.assertEqual(stale.status_code,409)
        self.assertEqual(self.client.post(f'/api/v1/cases/{rid}/revision',json={'version':1,'cause':'待核实','reason':'先核对'}).status_code,200)
        with patch('teaching_platform.service.evaluate_rules_v2',side_effect=AssertionError('不能重算历史')),patch('gel_image_assistant.request_observation',side_effect=AssertionError('不能自动请求')):
            self.assertEqual(self.client.get(f'/api/v1/cases/{rid}').status_code,200)
            self.assertEqual(self.client.get(f'/api/v1/cases/{rid}/report').status_code,200)

    def test_task_knowledge_frozen_and_atomic(self):
        teacher=self.teacher();uid=next(iter(self.service.knowledge.entities))
        payload={'title':'PCR任务','instructions':'先看知识再实验','knowledge_ids':[uid],'knowledge_note':'查看关联依据'}
        task=teacher.post('/api/v1/teacher/tasks',json=payload).json()
        self.assertEqual(task['knowledge']['items'][0]['id'],uid)
        old=self.client.get('/api/v1/tasks/'+task['code']).json()
        second=teacher.post('/api/v1/teacher/tasks',json={**payload,'parent_task_id':task['id'],'instructions':'新的说明'}).json()
        self.assertEqual(second['version'],2);self.assertEqual(self.client.get('/api/v1/tasks/'+task['code']).json(),old)
        with patch('teaching_platform.service.workflow.text',side_effect=lambda value,label,*a,**kw:(_ for _ in ()).throw(ValueError('参考冻结失败')) if label=='知识阅读提示' else value):
            self.assertEqual(teacher.post('/api/v1/teacher/tasks',json=payload).status_code,400)
        self.assertEqual(len(teacher.get('/api/v1/teacher/tasks').json()),2)

    def test_upload_validation_original_preserved_and_no_key_safe(self):
        created,_=self.create();rid=created['id']
        self.assertEqual(self.client.post(f'/api/v1/cases/{rid}/image',files={'file':('bad.png',b'bad','image/png')}).status_code,400)
        self.assertEqual(self.client.post(f'/api/v1/cases/{rid}/image',files={'file':('gel.png',self.png(),'image/png')}).status_code,200)
        self.assertEqual(self.client.post(f'/api/v1/cases/{rid}/image',files={'file':('gel.png',self.png(),'image/png')}).status_code,400)
        mapping=[{'lane_id':1,'role':'身份未确认'}]
        preview=self.client.post(f'/api/v1/cases/{rid}/gel/preview',json={'mapping':mapping}).json()
        response=self.client.post(f'/api/v1/cases/{rid}/gel/observe',json={'mapping':mapping,'consent':True,'context_key':preview['context_key']})
        self.assertEqual(response.json()['status'],'unconfigured')
        detail=self.client.get(f'/api/v1/cases/{rid}').json();self.assertEqual(detail['gel']['runs'],[])

    def test_legacy_backup_and_readonly_snapshot(self):
        path=self.root/'old.db';case_storage.init_database(path)
        case_storage.save_record(path,'无条带',None,None,None,'未观察','未观察','','旧字符串',student_access_code='old-private',raw_case={'data_origin':'真实课堂'})
        from teaching_platform.service import Service
        service=Service(path,self.root/'old-images',self.service.knowledge);service.initialize()
        self.assertTrue(path.with_name(path.name+'.before-unified-platform.bak').is_file())
        with w.connection(path) as conn:self.assertEqual(conn.execute('SELECT diagnosis_result FROM diagnosis_records').fetchone()[0],'旧字符串')
        restored=self.root/'restored.db';shutil.copyfile(path.with_name(path.name+'.before-unified-platform.bak'),restored)
        old=Service(restored,self.root/'restored-images',self.service.knowledge);old.initialize()
        with patch('teaching_platform.service.evaluate_rules_v2',side_effect=AssertionError('历史不能重算')):
            self.assertEqual(old.detail(1,'old-private')['diagnosis_result'],'旧字符串')

    def test_evaluation_reference_permissions_and_mocked_observation(self):
        teacher=self.teacher()
        uploaded=teacher.post('/api/v1/teacher/evaluations/image',files={'file':('gel.png',self.png(),'image/png')}).json()
        mapping=[{'lane_id':1,'role':'样本'}]
        preview=teacher.post('/api/v1/teacher/evaluations/preview',json={**uploaded,'mapping':mapping}).json()
        reference={'quality':'可辨','quality_issues':[],'lanes':[{'lane_id':1,'band_count':None,'pattern':'无法确认','position':'无法确认','brightness':'无法确认'}]}
        body={**uploaded,'mapping':mapping,'context_key':preview['context_key'],'reference':reference,'family':'qa-family','split':'独立验收集','quality':'清晰','independent_consent':True}
        response=teacher.post('/api/v1/teacher/evaluations',json=body);self.assertEqual(response.status_code,200,response.text);sid=response.json()['id']
        self.assertEqual(self.client.get(f'/api/v1/teacher/evaluations/{sid}/preview').status_code,401)
        image=teacher.get(f'/api/v1/teacher/evaluations/{sid}/preview');self.assertEqual(image.headers['content-type'],'image/png')
        self.assertEqual(teacher.post(f'/api/v1/teacher/evaluations/{sid}/observe',json={'consent':False}).status_code,400)
        candidate={'status':'success','observations':reference,'raw_response':json.dumps(reference),'model_returned':'deepseek-flash','usage':{}}
        with patch('gel_image_assistant.request_observation',return_value=candidate) as model:
            self.assertEqual(teacher.post(f'/api/v1/teacher/evaluations/{sid}/observe',json={'consent':True}).status_code,200)
            model.assert_called_once()
        sample=teacher.get('/api/v1/teacher/evaluations').json()[0]
        self.assertIsNone(sample['comparisons'][0]['参考条带数'])
        self.assertEqual(json.loads(sample['reference_json']),reference)

    def test_guest_session_replay_and_tampered_payload(self):
        self.assertEqual(self.client.post('/api/v1/session/guest',json={}).status_code,200)
        created,payload=self.create()
        self.assertEqual(self.client.post('/api/v1/cases',json=payload).json(),created)
        self.assertEqual(self.client.post('/api/v1/cases',json={**payload,'description':'改动'}).status_code,409)


    def test_twenty_concurrent_isolated_students(self):
        def submit(i):
            client=TestClient(self.app);client.headers['X-Teaching-Request']='1'
            response=client.post('/api/v1/cases',json={'request_id':f'{i:032d}','abnormality':'无条带','student_initial_hypothesis':'待核对','group_code':str(i)})
            if response.status_code!=200:return response.status_code
            image=client.post(f"/api/v1/cases/{response.json()['id']}/image",files={'file':('gel.png',self.png(),'image/png')})
            return image.status_code
        with ThreadPoolExecutor(max_workers=20) as pool:statuses=list(pool.map(submit,range(20)))
        self.assertEqual(statuses,[200]*20)
        with w.connection(self.service.db) as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM diagnosis_records').fetchone()[0],20)


class KnowledgeTests(unittest.TestCase):
    def test_reorder_keeps_ids_missing_not_substituted_and_no_false_verified_edge(self):
        raw={'v':'test','pw':[{'n':'糖酵解'}],'met':[{'n':'丙酮酸','en':'pyruvate','k':'C00022','pw':[0],'P':[[0,'cat']]}],
             'prot':[{'n':'丙酮酸激酶','up':'P14618','pw':[0]}],'gene':[{'n':'PKM','nc':'5315','pw':[0]}]}
        one=build(raw);two=build(copy.deepcopy(raw))
        self.assertEqual(one,two)
        self.assertEqual(one['edges'][0]['status'],'待核实')
        self.assertNotEqual(one['legacy_ids']['p0'],one['legacy_ids']['w0'])
        changed=copy.deepcopy(raw);changed['prot'].append({'n':'另一酶','up':'P00000','pw':[]});changed['prot'].reverse();changed['met'][0]['P']=[[1,'cat']]
        after=build(changed)
        self.assertEqual(one['legacy_ids']['p0'],after['legacy_ids']['p1'])
        frozen=build(changed,one['legacy_ids'])
        self.assertEqual(frozen['legacy_ids']['p0'],one['legacy_ids']['p0'])
        network=Knowledge();self.assertRaises(ValueError,network.detail,'gone-not-remapped')


if __name__=='__main__':unittest.main()
