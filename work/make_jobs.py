import csv, json, yaml, collections, os
q=[r for r in csv.DictReader(open('data/graph/fetch_queue.csv',encoding='utf-8-sig')) if not r['kind'].startswith('보류')]
idx={}
for r in csv.DictReader(open('data/raw/graduation_index_all.csv',encoding='utf-8-sig')):
    idx[(r['host'],r['id'])]=r
cfg=yaml.safe_load(open('crawler/sites_depts.yaml'))['boards']
main=yaml.safe_load(open('crawler/sites.yaml'))
done={f.split('.')[0] for f in os.listdir('data/extracted')}
jobs=collections.defaultdict(list); miss=[]
for r in q:
    src=r['rep'].split(':')[1]; key=f"{src}_{r['id']}"
    if key in done: continue
    ir=idx.get((r['host'],r['id']),{})
    bname=ir.get('board','')
    cands=[b for b in cfg if b['base'].endswith(r['host'])]
    b=next((b for b in cands if b['board']==bname),None) or (cands[0] if len(cands)==1 else None)
    if r['host']=='www.sookmyung.ac.kr':
        url=f"https://www.sookmyung.ac.kr/kr/news/notice.do?mode=view&articleNo={r['id']}"; eng='sm_cms'
    elif b is None:
        miss.append((key,r['host'],bname,[c['board'] for c in cands])); continue
    elif b['engine']=='k2web':
        url=f"{b['base']}{b['path'].replace('artclList.do','')}{r['id']}/artclView.do"; eng='k2web'
    elif b['engine']=='sm_cms':
        url=f"{b['base']}{b['path']}?mode=view&articleNo={r['id']}"; eng='sm_cms'
    else:
        miss.append((key,r['host'],bname,b['engine'])); continue
    jobs[r['host']].append({'key':key,'url':url,'eng':eng,'title':r['title']})
json.dump(jobs,open('work/jobs.json','w'),ensure_ascii=False,indent=0)
print(sum(map(len,jobs.values())),'jobs',len(jobs),'hosts'); print('miss',len(miss))
for m in miss: print(m)
