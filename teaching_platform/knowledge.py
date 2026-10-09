"""版本化只读知识资源。"""
import json
from collections import defaultdict
from pathlib import Path
from .config import ROOT


class Knowledge:
    def __init__(self, path=None):
        data=json.loads(Path(path or ROOT/'knowledge/network.json').read_text(encoding='utf-8'))
        self.version=data['version'];self.entities={e['id']:e for e in data['entities']}
        self.legacy=data['legacy_ids'];self.notice=data['notice'];self.adj=defaultdict(list)
        for edge in data['edges']:self.adj[edge['from']].append(edge)

    def summary(self,e):
        return {k:e[k] for k in ('id','name','english','kind')}

    def search(self,q='',kind='',offset=0,limit=30):
        query=q.strip().lower()
        found=[e for e in self.entities.values() if (not kind or e['kind']==kind) and (not query or query in e['search'] or query in e['name'].lower())]
        found.sort(key=lambda e:(query not in (e['name'].lower(), e['english'].lower()),e['name']))
        return {'items':[self.summary(e) for e in found[offset:offset+limit]],'total':len(found),'version':self.version}

    def detail(self,uid):
        if uid not in self.entities:raise ValueError('该词条未收录或已不能对应，请重新查询；不会自动替换为其他词条。')
        e=self.entities[uid]
        relations=[{**r,'target':self.summary(self.entities[r['to']])} for r in self.adj[uid]]
        members=[self.summary(x) for x in self.entities.values() if uid in x['pathways']] if e['kind']=='pw' else []
        return {**e,'search':None,'pathways':[self.summary(self.entities[p]) for p in e['pathways']],
                'relations':relations,'members':members,'version':self.version,'notice':self.notice}

    def snapshot(self,ids):
        if len(ids)>30 or len(set(ids))!=len(ids):raise ValueError('关联词条最多30项且不能重复。')
        return {'version':self.version,'items':[self.summary(self.entities[uid]) for uid in ids if uid in self.entities]}
