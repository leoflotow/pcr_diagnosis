"""原知识源表构建器：只处理指定的知识工作簿，不包含教学数据。"""
import io, re, json, os
from collections import defaultdict, Counter
from pathlib import Path
import argparse
import openpyxl


def build(source, destination):
    SRC = str(source)
    DST = str(destination)
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)

    def load(sheet):
        ws = wb[sheet]
        rows = ws.iter_rows(values_only=True)
        header = list(next(rows))
        d = []
        for r in rows:
            v = list(r)
            if all(x is None or str(x).strip() == "" for x in v):
                continue
            d.append({header[i]: v[i] for i in range(len(header))})
        return d

    raw_met = load("代谢物表")
    raw_prot = load("蛋白质表")
    raw_gene = load("基因表")

    def S(v):
        if v is None:
            return ""
        s = str(v).strip()
        return "" if s.lower() in ("nan", "none", "-", "n/a", "n", "a", "null") else s

    def key(s):
        return re.sub(r"[\s\-_()（）·]", "", str(s or "")).lower()

    # ---------------- 通路归一化 ----------------
    RULES = [
        ("糖酵解", r"糖酵解|glycolys|EMP途径|无氧酵解|无氧糖酵解|葡萄糖代谢"),
        ("糖异生", r"糖异生|gluconeo|Cori"),
        ("三羧酸循环", r"三羧酸|TCA|柠檬酸循环|krebs"),
        ("氧化磷酸化", r"氧化磷酸化|OXPHOS|电子传递链|呼吸链|复合体 ?[IV]"),
        ("磷酸戊糖途径", r"磷酸戊糖|戊糖磷酸|PPP|HMP"),
        ("糖原代谢", r"糖原|glycogen"),
        ("脂肪酸代谢", r"脂肪酸|β氧化|β-氧化|脂代谢|脂质代谢|FAO|脂肪分解|脂肪生成|甘油三酯|脂解|酰基肉碱|酮体"),
        ("胆固醇与类固醇", r"胆固醇|类固醇|甲羟戊酸|甾醇|sterol|鲨烯|胆汁酸"),
        ("磷脂与鞘脂", r"磷脂|鞘脂|甘油磷|膜磷脂|花生四烯酸|类花生酸|前列腺素|白三烯|脂氧合酶|环氧合酶"),
        ("氨基酸代谢", r"氨基酸|尿素循环|鸟氨酸|精氨基|BCAA|支链|谷氨酰|天冬氨|丙氨酸|色氨酸|酪氨酸|苯丙|甲硫氨酸|丝氨酸|甘氨酸|半胱|脯氨酸|赖氨酸|组氨酸|肌酸"),
        ("一碳代谢", r"一碳|叶酸|甲硫氨酸循环|SAM|同型半胱|甲基化"),
        ("核苷酸代谢", r"嘌呤|嘧啶|核苷酸|核酸合成|DNA合成|尿酸|dNTP|cAMP|cGMP"),
        ("血红素与卟啉", r"血红|卟啉|胆红|铁硫|ALA合酶"),
        ("光合作用", r"光合|Calvin|卡尔文|Rubisco|碳反应|光反应|暗反应"),
        ("线粒体与能量", r"线粒体|能量代谢|代谢调节|AMPK|UPRmt|嵴|呼吸"),
        ("氧化还原与抗氧化", r"抗氧化|氧化还原|谷胱甘肽|ROS|氧化应激|NADPH氧化酶|过氧化物|SOD|过氧化氢"),
        ("信号转导", r"信号|RTK|GPCR|MAPK|PI3K|AKT|Wnt|Notch|JAK|STAT|TGF|Hedgehog|NF-?κB|激酶级联|核受体|胰岛素信号|内分泌|生长因子|受体|第二信使|磷酸化级联"),
        ("表观遗传", r"表观|组蛋白|染色质|去乙酰化|乙酰转移|DNA去甲基化|miRNA|lncRNA|非编码RNA|甲基转移酶"),
        ("细胞周期与凋亡", r"细胞周期|凋亡|自噬|增殖|CDK|p53|有丝分裂|衰老|铁死亡|焦亡"),
        ("免疫与炎症", r"免疫|炎症|NF|B细胞|T细胞|TLR|细胞因子|补体|巨噬|趋化"),
        ("神经与突触", r"神经|突触|神经递质|多巴胺|胆碱能|谷氨酸受体|GABA|昼夜节律|睡眠|癫痫|阿尔茨海默|帕金森|神经退行"),
        ("转运与膜运输", r"转运|运输|通道|离子泵|载体|SLC|ABC转运|胞吞|外排"),
        ("蛋白合成与降解", r"蛋白合成|翻译|核糖体|泛素|蛋白酶体|折叠|UPR|内质网|分泌"),
        ("疾病与表型", r"癌|肿瘤|肥胖|糖尿病|NAFLD|脂肪肝|代谢综合征|心血管|动脉粥样|高血压|罕见病|遗传病|耐药"),
    ]

    def canon_path(p):
        s = str(p or "").strip()
        if not s or s in ("-", "N/A", "nan"):
            return None
        for name, pat in RULES:
            if re.search(pat, s, re.I):
                return name
        return None

    def paths_of(item, fields):
        res, raws = set(), []
        for f in fields:
            raw = str(item.get(f) or "")
            raw = raw.replace("；", ";").replace("，", ";").replace(",", ";").replace("、", ";")
            for piece in raw.split(";"):
                piece = piece.strip()
                if not piece or piece in ("-", "N/A", "nan"):
                    continue
                raws.append(piece)
                c = canon_path(piece)
                if c:
                    res.add(c)
        return res, raws

    MET_F = ["代谢通路 1", "代谢通路 2", "所涉及的代谢通路"]
    PROT_F = ["生物学过程", "所涉及的代谢通路"]
    GENE_F = ["所涉及的代谢通路和疾病"]

    all_pw = []
    pw_index = {}

    def pw_id(name):
        if name not in pw_index:
            pw_index[name] = len(all_pw)
            all_pw.append({"n": name, "m": 0, "p": 0, "g": 0})
        return pw_index[name]

    def num(v):
        try:
            f = float(str(v).strip())
            return int(f) if f == int(f) else f
        except Exception:
            return ""

    def toint(v):
        try:
            return int(float(str(v).strip()))
        except Exception:
            return None

    # ---------------- 载入清洗 ----------------
    mets, prots, genes = [], [], []

    for r in raw_met:
        m = {
            "n": S(r.get("中文名")), "en": S(r.get("英文名")), "al": S(r.get("别名")),
            "f": S(r.get("分子式")), "w": num(r.get("分子量")), "c": S(r.get("分类")),
            "d": S(r.get("生物学作用")),
            "p1": S(r.get("代谢通路 1")), "e1": S(r.get("通路 1 关键酶")),
            "p2": S(r.get("代谢通路 2")), "e2": S(r.get("通路 2 关键酶")),
            "k": S(r.get("KEGG_ID")), "pb": S(r.get("PubChem_ID")), "hmdb": S(r.get("HMDB_ID")),
            "ao": S(r.get("其他生物学作用")),
        }
        ps, raws = paths_of(r, MET_F)
        for x in (m["p1"], m["p2"]):
            c = canon_path(x)
            if c:
                ps.add(c)
        m["_pw"] = ps
        m["_raws"] = raws
        mets.append(m)

    for r in raw_prot:
        p = {
            "n": S(r.get("中文名")), "en": S(r.get("英文名")), "g": S(r.get("基因名")),
            "w": num(r.get("分子量")), "aa": num(r.get("氨基酸数")), "pi": num(r.get("等电点")),
            "sb": S(r.get("亚基组成")), "loc": S(r.get("细胞定位")),
            "fn": S(r.get("生理功能")), "d": S(r.get("生物学过程")),
            "dis": S(r.get("相关疾病")),
            "up": S(r.get("UniProt_ID")), "nc": S(r.get("NCBI_Gene_ID")), "pdb": S(r.get("PDB_ID")),
            "ao": S(r.get("其他生物学功能")),
        }
        ps, raws = paths_of(r, PROT_F)
        p["_pw"] = ps
        p["_raws"] = raws
        prots.append(p)

    for r in raw_gene:
        g = {
            "n": S(r.get("中文名")), "en": S(r.get("英文名")), "s": S(r.get("基因符号")),
            "chr": S(r.get("染色体位置")), "ptn": S(r.get("编码蛋白")), "up": S(r.get("蛋白 UniProt_ID")),
            "cds": num(r.get("CDS 长度")), "ex": num(r.get("外显子数")), "tx": S(r.get("转录本 ID")),
            "nc": S(r.get("NCBI_Gene_ID")), "es": S(r.get("Ensembl_ID")),
            "d": S(r.get("所涉及的代谢通路和疾病")), "ao": S(r.get("其他生物学功能")),
        }
        ps, raws = paths_of(r, GENE_F)
        g["_pw"] = ps
        g["_raws"] = raws
        genes.append(g)

    log = io.StringIO()

    # 去重 (按中文名+英文名, 保留首次出现)
    def dedup(arr, label):
        seen, out = set(), []
        for it in arr:
            k = key(it["n"]) + "|" + key(it["en"])
            if k in seen:
                continue
            seen.add(k)
            out.append(it)
        if len(out) != len(arr):
            log.write("dedup %s: %d -> %d\n" % (label, len(arr), len(out)))
        return out

    mets = dedup(mets, "met")
    prots = dedup(prots, "prot")
    genes = dedup(genes, "gene")

    log.write("loaded met=%d prot=%d gene=%d\n" % (len(mets), len(prots), len(genes)))

    # 通路 id 化
    for m in mets:
        m["pw"] = [pw_id(p) for p in sorted(m["_pw"])]
        for i in m["pw"]:
            all_pw[i]["m"] += 1
    for p in prots:
        p["pw"] = [pw_id(x) for x in sorted(p["_pw"])]
        for i in p["pw"]:
            all_pw[i]["p"] += 1
    for g in genes:
        g["pw"] = [pw_id(x) for x in sorted(g["_pw"])]
        for i in g["pw"]:
            all_pw[i]["g"] += 1

    # ---------------- 索引 ----------------
    gene_by_ncbi = defaultdict(list)
    gene_by_sym = defaultdict(list)
    gene_by_up = defaultdict(list)
    for i, g in enumerate(genes):
        n = toint(g["nc"])
        if n is not None:
            gene_by_ncbi[n].append(i)
        if g["s"]:
            gene_by_sym[key(g["s"])].append(i)
            for pc in re.split(r"[/;,]", g["s"]):
                pc = pc.strip()
                if pc:
                    gene_by_sym[key(pc)].append(i)
        if g["up"]:
            gene_by_up[g["up"].upper()].append(i)

    prot_by_up = defaultdict(list)
    prot_zn = []
    for i, p in enumerate(prots):
        if p["up"]:
            prot_by_up[p["up"].upper()].append(i)
        prot_zn.append((i, p["n"], key(p["n"])))

    # ---------------- 1) prot -> gene ----------------
    prot2gene = defaultdict(list)   # protIdx -> [(geneIdx, rel)]
    for i, p in enumerate(prots):
        found = {}
        n = toint(p["nc"])
        if n is not None and n in gene_by_ncbi:
            for gi in gene_by_ncbi[n]:
                found[gi] = "ncbi"
        for piece in re.split(r"[/;,]", p["g"]):
            pc = piece.strip()
            if not pc:
                continue
            k = key(pc)
            if k in gene_by_sym:
                for gi in gene_by_sym[k]:
                    found.setdefault(gi, "sym")
        if p["up"] and p["up"].upper() in gene_by_up:
            for gi in gene_by_up[p["up"].upper()]:
                found.setdefault(gi, "uniprot")
        if p["up"] and p["up"].upper() in prot_by_up:
            pass
        for gi, rel in found.items():
            prot2gene[i].append([gi, rel])

    hit_pg = sum(1 for i in range(len(prots)) if prot2gene[i])
    log.write("prot->gene: %d/%d (%.1f%%)\n" % (hit_pg, len(prots), 100.0 * hit_pg / len(prots)))

    # gene 编码的蛋白 (反向)
    gene2prot = defaultdict(list)
    for pi, lst in prot2gene.items():
        for gi, rel in lst:
            gene2prot[gi].append([pi, rel])

    # ---------------- 2) met -> prot (酶名) ----------------
    def core_of(k):
        return re.sub(r"(黄素蛋白|铁硫|脱氢酶|还原酶|合酶|激酶|羧化酶|转移酶|水解酶|家族|同工酶|复合体|型|调控蛋白|调节蛋白|e1|e2|e3).*$", "", k)

    def match_prot(enz):
        """返回 protIdx 列表"""
        k = key(enz)
        if not k:
            return []
        exact = [i for i, zn, zk in prot_zn if zk == k]
        if exact:
            return exact
        pref = [i for i, zn, zk in prot_zn if zk.startswith(k) and len(k) >= 3]
        if pref:
            return pref
        rev = [i for i, zn, zk in prot_zn if len(zk) >= 4 and k.startswith(zk)]
        if rev:
            return rev
        ck = core_of(k)
        # 防止过宽匹配: 要求核名>=4字 且为蛋白名前缀 (避免“丙酮酸羧化酶”误命中所有含“丙酮酸”的蛋白)
        if len(ck) >= 4:
            inc = [i for i, zn, zk in prot_zn if core_of(zk) == ck]
            if inc:
                return inc
            sub = [i for i, zn, zk in prot_zn if zk.startswith(ck)]
            if sub:
                return sub
        return []

    met2prot = defaultdict(list)   # metIdx -> [(protIdx, rel)]
    enz_stat = Counter()
    for i, m in enumerate(mets):
        found = {}
        for fld, pwy in (("e1", m["p1"]), ("e2", m["p2"])):
            raw = m[fld]
            if raw in ("", "N/A"):
                continue
            for piece in re.split(r"[;,、/]", raw):
                piece = piece.strip()
                if not piece or piece in ("-", "N/A", "nan"):
                    continue
                enz_stat["total"] += 1
                hits = match_prot(piece)
                if hits:
                    enz_stat["hit"] += 1
                    for pi in hits:
                        found.setdefault(pi, "cat")   # catalyzed
        for pi, rel in found.items():
            met2prot[i].append([pi, rel])

    cov = sum(1 for i in range(len(mets)) if met2prot[i])
    log.write("met->prot: %d/%d mets (%.1f%%); enzyme mentions %d hit %d\n"
              % (cov, len(mets), 100.0 * cov / len(mets), enz_stat["total"], enz_stat["hit"]))

    # prot 作用的代谢物 (反向)
    prot2met = defaultdict(list)
    for mi, lst in met2prot.items():
        for pi, rel in lst:
            prot2met[pi].append([mi, rel])

    # ---------------- 3) 同通路弱关联 ----------------
    pw2met = defaultdict(list)
    pw2prot = defaultdict(list)
    pw2gene = defaultdict(list)
    for i, m in enumerate(mets):
        for pi_ in m["pw"]:
            pw2met[pi_].append(i)
    for i, p in enumerate(prots):
        for pi_ in p["pw"]:
            pw2prot[pi_].append(i)
    for i, g in enumerate(genes):
        for pi_ in g["pw"]:
            pw2gene[pi_].append(i)

    MAX_CO = 8
    def co_items(idx, kind, limit=MAX_CO):
        """返回同通路同类实体 [(idx, rel, pw)] 排除自身"""
        src = {"m": mets, "p": prots, "g": genes}[kind]
        pool = {"m": pw2met, "p": pw2prot, "g": pw2gene}[kind]
        res = []
        for pwid in src[idx]["pw"]:
            for j in pool[pwid]:
                if j == idx:
                    continue
                res.append((j, "co", pwid))
        # 去重取最优
        best = {}
        for j, rel, pwid in res:
            if j not in best:
                best[j] = pwid
        return [[j, "co", best[j]] for j in list(best.keys())[:limit]]

    # 同通路跨类型
    def cross_pw(idx, kind, target, limit=10):
        src = {"m": mets, "p": prots, "g": genes}[kind]
        pool = {"m": pw2met, "p": pw2prot, "g": pw2gene}[target]
        res = []
        for pwid in src[idx]["pw"]:
            for j in pool[pwid]:
                res.append([j, "co", pwid])
        seen = set()
        out = []
        for j, rel, pwid in res:
            if j in seen:
                continue
            seen.add(j)
            out.append([j, "co", pwid])
            if len(out) >= limit:
                break
        return out

    # ---------------- 组装边 ----------------
    for i in range(len(mets)):
        mets[i]["P"] = sorted(met2prot.get(i, []), key=lambda x: x[0])
        # 由蛋白带出的基因
        gs = {}
        for pi, rel in mets[i]["P"]:
            for gi, grel in prot2gene.get(pi, []):
                gs.setdefault(gi, "via")
        # UniProt 直接互引
        mets[i]["G"] = sorted([[g, r] for g, r in gs.items()], key=lambda x: x[0])
        mets[i]["M"] = co_items(i, "m", 8)
        mets[i]["CP"] = cross_pw(i, "m", "p", 10)
        mets[i]["CG"] = cross_pw(i, "m", "g", 10)

    for i in range(len(prots)):
        prots[i]["M"] = sorted(prot2met.get(i, []), key=lambda x: x[0])
        prots[i]["G"] = sorted(prot2gene.get(i, []), key=lambda x: x[0])
        prots[i]["P"] = co_items(i, "p", 8)
        prots[i]["CM"] = cross_pw(i, "p", "m", 10)
        prots[i]["CG"] = cross_pw(i, "p", "g", 10)

    for i in range(len(genes)):
        genes[i]["P"] = sorted(gene2prot.get(i, []), key=lambda x: x[0])
        ms = {}
        for pi, rel in genes[i]["P"]:
            for mi, mrel in prot2met.get(pi, []):
                ms.setdefault(mi, "via")
        genes[i]["M"] = sorted([[m, r] for m, r in ms.items()], key=lambda x: x[0])
        genes[i]["G"] = co_items(i, "g", 8)
        genes[i]["CM"] = cross_pw(i, "g", "m", 10)
        genes[i]["CP"] = cross_pw(i, "g", "p", 10)

    edge_n = sum(len(m["P"]) + len(m["G"]) + len(m["M"]) for m in mets) \
           + sum(len(p["M"]) + len(p["G"]) + len(p["P"]) for p in prots) \
           + sum(len(g["P"]) + len(g["M"]) + len(g["G"]) for g in genes)
    log.write("total edges: %d\n" % edge_n)

    # ---------------- 搜索键 ----------------
    def strip_underscore(d):
        return {k: v for k, v in d.items() if not k.startswith("_")}

    for arr in (mets, prots, genes):
        for it in arr:
            parts = [it.get("n", ""), it.get("en", ""), it.get("al", ""), it.get("s", ""), it.get("g", ""), it.get("ptn", "")]
            it["q"] = " ".join(x for x in parts if x).lower()

    # ---------------- 输出 ----------------
    for m in mets:
        m.pop("_pw", None); m.pop("_raws", None)
    for p in prots:
        p.pop("_pw", None); p.pop("_raws", None)
    for g in genes:
        g.pop("_pw", None); g.pop("_raws", None)

    data = {
        "v": "1.0",
        "stat": {"met": len(mets), "prot": len(prots), "gene": len(genes),
                 "pw": len(all_pw), "edge": edge_n,
                 "covP": cov, "covG": hit_pg},
        "pw": all_pw,
        "met": mets,
        "prot": prots,
        "gene": genes,
    }

    with open(DST, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(DST)
    log.write("output: %s (%.1f KB)\n" % (DST, size / 1024.0))

    print(log.getvalue())
    wb.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'knowledge/source/app_data.json')
    args=parser.parse_args()
    build(args.input,args.output)
