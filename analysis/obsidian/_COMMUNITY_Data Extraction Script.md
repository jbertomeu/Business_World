---
type: community
cohesion: 1.00
members: 2
---

# Data Extraction Script

**Cohesion:** 1.00 - tightly connected
**Members:** 2 nodes

## Members
- [[Extract panel data from snapshots for ν+6 20Y analysis.]] - rationale - analysis\extract_data.py
- [[extract_data.py]] - code - analysis\extract_data.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Data_Extraction_Script
SORT file.name ASC
```
