# Search URL Builder

Instead of pasting full search URLs, use CLI flags. JobPilot builds the correct URL for each site.

## LinkedIn jobs

URL template:
```
https://www.linkedin.com/jobs/search/?keywords={keywords}&f_AL=true{params}
```

`f_AL=true` (Easy Apply) is always added automatically.

| CLI flag | URL param | Values |
|----------|-----------|--------|
| `--keywords` | `keywords=` | any text |
| `--date-posted 24h` | `f_TPR=r86400` | `24h`, `week`, `month` |
| `--date-posted any` | *(omitted)* | no time filter |
| `--workplace remote` | `f_WT=2` | `on-site`→1, `remote`→2, `hybrid`→3 |
| `--location Brasil` | `location=Brasil` | any text |
| `--experience mid-senior` | `f_E=4` | `internship`→1, `entry`→2, `associate`→3, `mid-senior`→4, `director`→5, `executive`→6 |

### Example

```bash
uv run main.py apply \
  --keywords "python backend" \
  --site linkedin \
  --date-posted 24h \
  --workplace remote \
  --location Brasil
```

Generates:
```
https://www.linkedin.com/jobs/search/?keywords=python+backend&f_AL=true&f_TPR=r86400&f_WT=2&location=Brasil
```

## LinkedIn people search (connect)

URL template:
```
https://www.linkedin.com/search/results/people/?keywords={keywords}{network}
```

| CLI flag | URL param | Values |
|----------|-----------|--------|
| `--keywords` | `keywords=` | any text |
| `--network F` | `network=["F"]` | `F`=1st, `S`=2nd, `O`=3rd+ |

```bash
uv run main.py connect --keywords "tech recruiter" --network S
```

Generates:
```
https://www.linkedin.com/search/results/people/?keywords=tech+recruiter&network=%5B%22S%22%5D
```

## Indeed

URL template:
```
https://br.indeed.com/jobs?q={keywords}&sc=0kf:attr(DSK7o)jt(fc){params}
```

Easy Apply filter is embedded in `sc=0kf:attr(DSK7o)jt(fc)`.

| CLI flag | URL param | Values |
|----------|-----------|--------|
| `--keywords` | `q=` | any text |
| `--date-posted 24h` | `fromage=1` | `24h`→1, `3d`→3, `week`→7, `14d`→14 |
| `--location Brasil` | `l=Brasil` | any text |

Note: Indeed only uses the Brazil domain (`br.indeed.com`).

## Glassdoor

Not supported by the builder (URL structure uses `.htm` pages and is complex to parameterize). Use `--url` directly:

```bash
uv run main.py apply --url "https://www.glassdoor.com/Job/..."
```

## Persistence

Search parameters (keywords, filters) are saved per site in `files/last_urls.json`:

```json
{
  "apply_linkedin": {
    "keywords": "python backend",
    "date_posted": "24h",
    "workplace": "remote",
    "location": "Brasil",
    "page": 3,
    "level": ["pleno"],
    "resume": "resume.txt"
  },
  "apply_indeed": {
    "keywords": "node.js",
    "date_posted": "week",
    "page": 1
  },
  "apply_last_site": "linkedin"
}
```

On subsequent runs without `--url` or `--keywords`, the saved params are used to rebuild the URL.
