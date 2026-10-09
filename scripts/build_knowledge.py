"""将原关联数据转换为稳定编号；不凭匹配算法声明已确认的生物关系。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = {'met': '代谢物', 'prot': '蛋白／酶', 'gene': '基因', 'pw': '通路'}
LABELS = {'n':'中文名','en':'英文名','al':'别名','f':'分子式','w':'分子量','c':'分类','d':'生物学作用／过程',
          'p1':'通路一','p2':'通路二','e1':'通路一关键酶（源表）','e2':'通路二关键酶（源表）',
          'k':'KEGG ID','pb':'PubChem ID','hmdb':'HMDB ID','ao':'补充功能','g':'基因名','aa':'氨基酸数',
          'pi':'等电点','sb':'亚基组成','loc':'细胞定位','fn':'生理功能','dis':'相关疾病',
          'up':'UniProt ID','nc':'NCBI Gene ID','pdb':'PDB ID','s':'基因符号','chr':'染色体位置',
          'ptn':'编码蛋白（源表）','cds':'CDS 长度','ex':'外显子数','tx':'转录本 ID','es':'Ensembl ID'}
BASIS = {'ncbi':('标识符匹配','待核实'), 'uniprot':('标识符匹配','待核实'),
         'sym':('名称匹配','待核实'), 'cat':('酶名称匹配（含模糊匹配）','待核实'),
         'via':('经蛋白间接关联','间接提示'), 'co':('同通路共现','同通路提示')}


def fingerprint(kind, item):
    # 有唯一外部标识时优先使用；多重/冲突标识保留名称以避免误合并。
    keys = {'met': ['k','pb','hmdb'], 'prot': ['up'], 'gene': ['nc','es'], 'pw': []}[kind]
    for key in keys:
        value = str(item.get(key) or '').strip()
        if value and not any(c in value for c in ';,/ '):
            return f'{kind}:{key}:{value.lower()}'
    return f"{kind}:name:{str(item.get('n','')).strip().lower()}:{str(item.get('en','')).strip().lower()}"


def build(raw, legacy_ids=None):
    entities, indices, legacy = {}, {}, {}
    for kind in KINDS:
        counts = {}
        for item in raw[kind]:
            fp = fingerprint(kind,item); counts[fp] = counts.get(fp,0)+1
        for index, item in enumerate(raw[kind]):
            fp = fingerprint(kind,item)
            if counts[fp]>1:
                fp += ':disambiguated:' + str(item.get('n','')) + ':' + str(item.get('en',''))
            uid = kind + '-' + hashlib.sha256(fp.encode()).hexdigest()[:20]
            if uid in entities:
                raise ValueError('发现无法消歧的词条，需人工处理后重新构建。')
            indices[(kind,index)] = uid
            legacy[{'met':'m','prot':'p','gene':'g','pw':'w'}[kind]+str(index)] = uid
            entities[uid] = {'id':uid,'kind':kind,'name':item['n'],'english':item.get('en',''),
                'fields':{LABELS[k]:v for k,v in item.items() if k in LABELS and v not in ('',None)},
                'species':'未知','source':'本地数据库 v20（整理来源，尚未逐条核实）',
                'pathways':[], 'search':' '.join(str(item.get(k,'')) for k in ('n','en','al','g','s','q')).lower()}
    edges = []
    for kind in ('met','prot','gene'):
        for index,item in enumerate(raw[kind]):
            uid = indices[kind,index]
            entities[uid]['pathways'] = [indices['pw',p] for p in item.get('pw',[])]
            for key,target in [('M','met'),('P','prot'),('G','gene'),('CM','met'),('CP','prot'),('CG','gene')]:
                for relation in item.get(key,[]):
                    basis,status = BASIS[relation[1]]
                    edges.append({'from':uid,'to':indices[target,relation[0]],'basis':basis,'status':status,
                                  'type':relation[1],'pathway':indices['pw',relation[2]] if len(relation)>2 else None})
    payload={'entities':list(entities.values()),'edges':edges,'legacy_ids':dict(legacy_ids) if legacy_ids is not None else legacy,'source_version':raw.get('v'),
             'notice':'关联不等于反应方向；自动匹配不等于已确认关系。物种与逐条来源尚待补齐。'}
    payload['version']=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
    return payload


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,default=ROOT/'knowledge/source/app_data.json');p.add_argument('--output',type=Path,default=ROOT/'knowledge/network.json');a=p.parse_args()
    frozen=ROOT/'knowledge/legacy_ids.json'
    legacy=json.loads(frozen.read_text(encoding='utf-8'))['ids'] if frozen.is_file() else None
    result=build(json.loads(a.input.read_text(encoding='utf-8-sig')),legacy);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f"知识数据：{len(result['entities'])} 个词条，{len(result['edges'])} 个有向关联记录；版本 {result['version']}")
