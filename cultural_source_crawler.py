#!/usr/bin/env python3
"""Config-driven single-source crawler for SETU-Culture."""
from __future__ import annotations
import argparse, csv, hashlib, html, json, os, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_CONFIG = Path(__file__).resolve().parent / "cultural_crawl_config.json"
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")
EUROPEANA_API_KEY = os.environ.get("EUROPEANA_API_KEY", "")
RUNTIME = {"user_agent": "SETU-Culture-Bot/1.0", "delay": 0.6}
FIELDS = ["record_id","source_id","source_name","source_type","evidence_class","source_tier","title","url","description","authors","publisher","publication_date","language","query_id","query_group","topic_query","target_cultures","seed_pair_id","configured_relationship_type","configured_shared_element","seed_notes","matched_queries_json","domains","rights_license","access_level","external_id","retrieved_at"]

def now(): return datetime.now(timezone.utc).isoformat()
def clean(v: Any) -> str:
    if isinstance(v, list): return "; ".join(clean(x) for x in v if x not in (None, ""))
    if isinstance(v, dict): return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return re.sub(r"\s+", " ", html.unescape(str(v or ""))).strip()

def get(url: str, params: dict[str, Any] | None = None, accept="application/json"):
    if params: url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": RUNTIME["user_agent"], "Accept": accept})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r: return r.read()
        except Exception as e:
            last = e
            if attempt < 3: time.sleep(min(15, 2 ** attempt))
    raise RuntimeError(f"GET failed for {url}: {last}")
def get_json(url, params=None): return json.loads(get(url, params).decode("utf-8", "replace"))
def get_text(url, params=None): return get(url, params, "text/html,application/xhtml+xml").decode("utf-8", "replace")
def inverted(index):
    return " ".join(word for _, word in sorted((p, w) for w, ps in (index or {}).items() for p in ps))

def make_record(source, query, title, url, description, **kw):
    url, external = clean(url), clean(kw.get("external_id"))
    identity = f"{source['id']}|{external or url or clean(title)}"
    match = {"query_id":query["id"],"query_group":query["group"],"query":query["text"],"target_cultures":query.get("cultures",[]),"seed_pair_id":query.get("seed_pair_id","")}
    return {"record_id":hashlib.sha256(identity.encode()).hexdigest()[:24],"source_id":source["id"],"source_name":source["name"],"source_type":source["type"],"evidence_class":source["evidence_class"],"source_tier":source["tier"],"title":clean(title),"url":url,"description":clean(description)[:50000],"authors":clean(kw.get("authors")),"publisher":clean(kw.get("publisher")),"publication_date":clean(kw.get("publication_date")),"language":clean(kw.get("language",source.get("language",""))),"query_id":query["id"],"query_group":query["group"],"topic_query":query["text"],"target_cultures":clean(query.get("cultures",[])),"seed_pair_id":query.get("seed_pair_id",""),"configured_relationship_type":query.get("relationship_type",""),"configured_shared_element":query.get("shared_element",""),"seed_notes":query.get("notes",""),"matched_queries_json":json.dumps([match],ensure_ascii=False),"domains":clean(kw.get("domains")),"rights_license":clean(kw.get("rights_license",source.get("default_license",""))),"access_level":source.get("access_level","metadata_only"),"external_id":external,"retrieved_at":now()}

def queries(config, groups):
    out=[]; scope=config.get("geographic_scope",[])
    if "cross_cultural" in groups:
        for i, text in enumerate(config.get("cross_cultural_queries",[]),1): out.append({"id":f"cross_{i:03d}","group":"cross_cultural","text":text,"cultures":[g["name"] for g in scope if re.search(rf"\b{re.escape(g['name'])}\b",text,re.I)]})
    if "seed_pairs" in groups:
        for s in config.get("seed_pairs",[]): out.append({"id":f"seed_{s['id']}","group":"seed_pairs","text":clean(f"{s.get('culture_a',{}).get('query','')} {s.get('culture_b',{}).get('query','')} {s.get('shared_element','')} transmission adaptation similarity differences origin"),"cultures":[],"seed_pair_id":s["id"],"relationship_type":s.get("relationship_type",""),"shared_element":s.get("shared_element",""),"notes":s.get("notes","")})
    if "geographic_pairs" in groups:
        for g in scope:
            if g["name"] == "India": continue
            for c in config.get("query_concepts",[]): out.append({"id":f"geo_{len(out):04d}","group":"geographic_pairs","text":f"India {g['name']} {c} cultural transmission similarity differences shared origin adaptation","cultures":["India",g["name"]]})
    if "local_context" in groups:
        for g in scope:
            for i, text in enumerate(g.get("local_queries",[]),1): out.append({"id":f"local_{g['name'].lower()}_{i}","group":"local_context","text":f"{text} cross-cultural transmission adaptation comparison","cultures":[g["name"]]})
    seen=set(); result=[]
    for q in out:
        if q["text"].lower() not in seen: seen.add(q["text"].lower()); result.append(q)
    return result

def crossref(s,q,n):
    p={"query.bibliographic":q["text"],"rows":n,"select":"DOI,title,author,publisher,published,abstract,URL"}; p["mailto"]=CONTACT_EMAIL if CONTACT_EMAIL else None; p={k:v for k,v in p.items() if v is not None}
    for x in get_json("https://api.crossref.org/works",p).get("message",{}).get("items",[]): yield make_record(s,q,(x.get("title") or [""])[0],x.get("URL") or "https://doi.org/"+clean(x.get("DOI")),re.sub(r"<[^>]+>"," ",clean(x.get("abstract"))),external_id=x.get("DOI"),authors=x.get("author"),publisher=x.get("publisher"),publication_date=x.get("published",{}).get("date-parts",[[""]])[0],language=x.get("language"))
def openalex(s,q,n):
    p={"search":q["text"],"per-page":n}; p["mailto"]=CONTACT_EMAIL if CONTACT_EMAIL else None; p={k:v for k,v in p.items() if v is not None}
    for x in get_json("https://api.openalex.org/works",p).get("results",[]):
        loc=x.get("primary_location") or {}; yield make_record(s,q,x.get("title"),loc.get("landing_page_url") or x.get("doi"),inverted(x.get("abstract_inverted_index")),external_id=x.get("id"),authors=[a.get("author",{}).get("display_name") for a in x.get("authorships",[])],publisher=(loc.get("source") or {}).get("display_name"),publication_date=x.get("publication_date"),language=x.get("language"),domains=[c.get("display_name") for c in x.get("concepts",[])[:10]])
def wikipedia(s,q,n):
    lang=s.get("language","en"); ep=f"https://{lang}.wikipedia.org/w/api.php"; data=get_json(ep,{"action":"query","format":"json","list":"search","srsearch":q["text"],"srlimit":n,"utf8":1})
    for item in data.get("query",{}).get("search",[]):
        title=item.get("title",""); page=get_json(ep,{"action":"query","format":"json","prop":"extracts|info","exintro":1,"explaintext":1,"inprop":"url","titles":title}); value=next(iter(page.get("query",{}).get("pages",{}).values()),{}); yield make_record(s,q,title,value.get("fullurl"),value.get("extract") or item.get("snippet"),external_id=value.get("pageid"),language=lang)
def archive(s,q,n):
    data=get_json("https://archive.org/advancedsearch.php",{"q":q["text"],"fl[]":["identifier","title","description","date","creator","language","licenseurl"],"rows":n,"output":"json"})
    for x in data.get("response",{}).get("docs",[]):
        i=x.get("identifier",""); yield make_record(s,q,x.get("title"),"https://archive.org/details/"+i,x.get("description"),external_id=i,authors=x.get("creator"),publication_date=x.get("date"),language=x.get("language"),rights_license=x.get("licenseurl"))
def europeana(s,q,n):
    if not EUROPEANA_API_KEY: raise RuntimeError("EUROPEANA_API_KEY is required")
    for x in get_json("https://api.europeana.eu/record/v2/search.json",{"wskey":EUROPEANA_API_KEY,"query":q["text"],"rows":n}).get("items",[]): yield make_record(s,q,(x.get("title") or [""])[0] if isinstance(x.get("title"),list) else x.get("title"),x.get("guid"),x.get("dcDescription") or x.get("edmPreview"),external_id=x.get("id"),language=x.get("language"),rights_license=x.get("rights"))
def met(s,q,n):
    for i in (get_json("https://collectionapi.metmuseum.org/public/collection/v1/search",{"q":q["text"],"hasImages":"true"}).get("objectIDs") or [])[:n]:
        x=get_json(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{i}"); d=" ".join(clean(x.get(k)) for k in ("objectName","culture","period","dynasty","medium","creditLine") if x.get(k)); yield make_record(s,q,x.get("title"),x.get("objectURL"),d,external_id=i,authors=x.get("artistDisplayName"),publication_date=x.get("objectDate"),domains=[x.get("department"),x.get("classification")],rights_license="public_domain" if x.get("isPublicDomain") else s.get("default_license"))
def wikidata(s,q,n):
    for x in get_json("https://www.wikidata.org/w/api.php",{"action":"wbsearchentities","format":"json","language":"en","uselang":"en","search":q["text"],"limit":n}).get("search",[]): yield make_record(s,q,x.get("label"),x.get("concepturi"),x.get("description"),external_id=x.get("id"),language="en",rights_license="CC0")
def html_meta(text):
    t=re.search(r"<title[^>]*>(.*?)</title>",text,re.I|re.S); d=re.search(r"<meta[^>]+(?:name|property)=[\"'](?:description|og:description)[\"'][^>]+content=[\"'](.*?)[\"']",text,re.I|re.S); return clean(re.sub(r"<[^>]+>"," ",t.group(1))) if t else "", clean(d.group(1)) if d else ""
def curated(s,q,n):
    for item in s.get("urls",[])[:n]:
        title, desc=html_meta(get_text(item["url"])); yield make_record(s,q,item.get("title") or title,item["url"],desc,external_id=item["url"],domains=[item.get("country"),item.get("region"),item.get("macro_region")])

CRAWLERS={"crossref":crossref,"openalex":openalex,"wikipedia":wikipedia,"internet_archive":archive,"europeana":europeana,"met_museum":met,"wikidata":wikidata,"unesco_heritage":curated,"curated_urls":curated}
def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--config",type=Path,default=DEFAULT_CONFIG); ap.add_argument("--out-dir",type=Path,default=Path("cultural_crawl_outputs")); ap.add_argument("--sources",default=""); ap.add_argument("--query-groups",default="cross_cultural,seed_pairs"); ap.add_argument("--limit-per-query",type=int,default=5); ap.add_argument("--max-queries",type=int,default=0); ap.add_argument("--sleep",type=float,default=None); a=ap.parse_args()
    started=now(); raw=a.config.read_bytes(); cfg=json.loads(raw); RUNTIME["user_agent"]=os.environ.get("CRAWLER_USER_AGENT",cfg.get("user_agent",RUNTIME["user_agent"])); RUNTIME["delay"]=a.sleep if a.sleep is not None else float(cfg.get("request_delay_seconds",.6)); qs=queries(cfg,{x.strip() for x in a.query_groups.split(",") if x.strip()}); qs=qs[:a.max_queries] if a.max_queries else qs; wanted={x.strip() for x in a.sources.split(",") if x.strip()}; sources=[s for s in cfg.get("sources",[]) if s.get("enabled") and (not wanted or s["id"] in wanted)]; a.out_dir.mkdir(parents=True,exist_ok=True); rows=[]; errors=[]; skipped=[]
    for s in sources:
        fn=CRAWLERS.get(s["type"])
        if not fn: skipped.append({"source_id":s["id"],"reason":f"unsupported source type: {s['type']}"}); continue
        if s["type"]=="europeana" and not EUROPEANA_API_KEY: skipped.append({"source_id":s["id"],"reason":"EUROPEANA_API_KEY not set"}); continue
        for q in qs:
            try: rows.extend(fn(s,q,max(1,a.limit_per_query)) or [])
            except Exception as e: errors.append({"source_id":s["id"],"query_id":q["id"],"error":str(e)})
            time.sleep(max(0,RUNTIME["delay"]))
    merged={}
    for r in rows:
        if r["record_id"] not in merged: merged[r["record_id"]]=r
        else:
            old=merged[r["record_id"]]; ms=json.loads(old["matched_queries_json"])+json.loads(r["matched_queries_json"]); old["matched_queries_json"]=json.dumps(list({(m["query_id"],m["query"]):m for m in ms}.values()),ensure_ascii=False)
    rows=sorted(merged.values(),key=lambda r:(r["source_id"],r["query_group"],r["title"])); (a.out_dir/"cultural_sources.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8"); (a.out_dir/"crawl_config_snapshot.json").write_bytes(raw)
    with (a.out_dir/"cultural_sources.jsonl").open("w",encoding="utf8") as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False)+"\n")
    with (a.out_dir/"cultural_sources.csv").open("w",encoding="utf8",newline="") as f: w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    report={"started_at":started,"finished_at":now(),"schema_version":cfg.get("schema_version"),"configuration_sha256":hashlib.sha256(raw).hexdigest(),"query_groups":a.query_groups,"query_count":len(qs),"sources":[s["id"] for s in sources],"record_count":len(rows),"errors":errors,"skipped_sources":skipped,"request_delay_seconds":RUNTIME["delay"],"contact_email_set":bool(CONTACT_EMAIL),"europeana_api_key_used":bool(EUROPEANA_API_KEY)}; (a.out_dir/"crawl_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8"); print(f"Collected {len(rows)} unique records into {a.out_dir}")
if __name__=="__main__": main()
