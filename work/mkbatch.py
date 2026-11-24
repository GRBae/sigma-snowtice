import json,sys
G=open('/home/claude/sigma/work/grab.js').read().strip()
j=json.load(open('/home/claude/sigma/work/jobs_cur.json'))
acts=[]
for pair in sys.argv[1:]:
    tab,host=pair.split('=')
    acts.append({"name":"javascript_tool","input":{"tabId":tab,"action":"javascript_exec","text":G+"\nawait window.__grab("+json.dumps(j[host])+")"}})
print(json.dumps(acts,ensure_ascii=False))
