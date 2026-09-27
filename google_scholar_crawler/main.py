from scholarly import scholarly
import json
from datetime import datetime, timezone
import os

scholar_id = os.environ["GOOGLE_SCHOLAR_ID"]
author = scholarly.search_author_id(scholar_id)
scholarly.fill(author, sections=["basics", "indices", "counts", "publications"])

author["updated"] = datetime.now(timezone.utc).isoformat()
author["publications"] = {
    p["author_pub_id"]: p
    for p in author.get("publications", [])
    if p.get("author_pub_id")
}

os.makedirs("google_scholar_crawler/results", exist_ok=True)
with open("google_scholar_crawler/results/gs_data.json", "w", encoding="utf-8") as f:
    json.dump(author, f, ensure_ascii=False)

shield = {
    "schemaVersion": 1,
    "label": "citations",
    "message": str(author.get("citedby", 0))
}
with open("google_scholar_crawler/results/gs_data_shieldsio.json", "w", encoding="utf-8") as f:
    json.dump(shield, f, ensure_ascii=False)
