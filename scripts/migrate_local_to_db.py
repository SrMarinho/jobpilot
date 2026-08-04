"""Migra dados locais JSON → Supabase (upsert — não apaga dados existentes)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.persistence.db import connection, jsonb

FILES = Path(".local/files")

_HIRED_PROFILES_DDL = """
CREATE TABLE IF NOT EXISTS hired_profiles (
    profile_url text PRIMARY KEY,
    name text, headline text, company text,
    top_skills jsonb, age_days int, role text,
    source text, scraped_at timestamptz
);
"""


def ensure_hired_profiles_table():
    with connection() as conn:
        conn.execute(_HIRED_PROFILES_DDL)
    print("✓ hired_profiles table ensured")


def migrate_rejected_jobs():
    path = FILES / "rejected_jobs.json"
    if not path.exists():
        print("  rejected_jobs.json not found, skip")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = skip = 0
    with connection() as conn:
        for job_id, rec in data.items():
            try:
                conn.execute(
                    """INSERT INTO rejected_jobs (job_id, title, url, rejected_at, reason, site)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (job_id) DO UPDATE SET
                         title=EXCLUDED.title, url=EXCLUDED.url,
                         rejected_at=EXCLUDED.rejected_at,
                         reason=EXCLUDED.reason, site=EXCLUDED.site""",
                    (
                        job_id,
                        rec.get("title"),
                        rec.get("url"),
                        rec.get("rejected_at"),
                        rec.get("reason"),
                        rec.get("site"),
                    ),
                )
                ok += 1
            except Exception as e:
                print(f"  WARN rejected_jobs {job_id}: {e}")
                skip += 1
    print(f"✓ rejected_jobs: {ok} upserted, {skip} errors")


def migrate_skills_gap():
    path = FILES / "skills_gap.json"
    if not path.exists():
        print("  skills_gap.json not found, skip")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = skip = 0
    with connection() as conn:
        for skill, rec in data.items():
            try:
                conn.execute(
                    """INSERT INTO skills_gap (skill, category, level, estimate, count, last_seen, month_counts)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (skill) DO UPDATE SET
                         category=EXCLUDED.category, level=EXCLUDED.level,
                         estimate=EXCLUDED.estimate, count=EXCLUDED.count,
                         last_seen=EXCLUDED.last_seen, month_counts=EXCLUDED.month_counts""",
                    (
                        skill,
                        rec.get("category"),
                        rec.get("level"),
                        rec.get("estimate"),
                        rec.get("count"),
                        rec.get("last_seen"),
                        jsonb(rec.get("month_counts") or {}),
                    ),
                )
                ok += 1
            except Exception as e:
                print(f"  WARN skills_gap {skill}: {e}")
                skip += 1
    print(f"✓ skills_gap: {ok} upserted, {skip} errors")


def migrate_hired_profiles():
    path = FILES / "hired_profiles.json"
    if not path.exists():
        print("  hired_profiles.json not found, skip")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    profiles = data.get("profiles", [])
    ok = skip = 0
    with connection() as conn:
        for rec in profiles:
            try:
                conn.execute(
                    """INSERT INTO hired_profiles
                         (profile_url, name, headline, company, top_skills, age_days, role, source, scraped_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (profile_url) DO UPDATE SET
                         name=EXCLUDED.name, headline=EXCLUDED.headline,
                         company=EXCLUDED.company, top_skills=EXCLUDED.top_skills,
                         age_days=EXCLUDED.age_days, role=EXCLUDED.role,
                         source=EXCLUDED.source, scraped_at=EXCLUDED.scraped_at""",
                    (
                        rec.get("profile_url"),
                        rec.get("name"),
                        rec.get("headline"),
                        rec.get("company"),
                        jsonb(rec.get("top_skills") or []),
                        rec.get("age_days"),
                        rec.get("role"),
                        rec.get("source", "posts"),
                        rec.get("scraped_at"),
                    ),
                )
                ok += 1
            except Exception as e:
                print(f"  WARN hired_profiles {rec.get('profile_url')}: {e}")
                skip += 1
    print(f"✓ hired_profiles: {ok} upserted, {skip} errors")


if __name__ == "__main__":
    print("=== migrate local JSON → Supabase ===")
    ensure_hired_profiles_table()
    migrate_rejected_jobs()
    migrate_skills_gap()
    migrate_hired_profiles()
    print("=== done ===")
