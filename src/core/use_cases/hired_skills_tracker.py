"""Tracker + agregador de perfis recém-contratados (feature `hired`).

Guarda um subconjunto por perfil (NÃO o perfil inteiro): suficiente p/ dedup,
expirar ≤3 meses e reagregar skill→contagem. O ranking de skills mais
frequentes entre contratados recentes é a saída pedida pelo usuário.

Persistência espelha `engaged_posts_tracker`: KeyedRepo (dedup por url) em modo
DB, JSON em `.local/files/hired_profiles.json` caso contrário.
"""

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from src.config.settings import files_dir, logger
from src.core.persistence.db import is_db_enabled
from src.core.persistence.keyed_repo import KeyedRepo
from src.core.use_cases.skills_tracker import _canonical_skill

HIRED_PROFILES_FILE = files_dir / "hired_profiles.json"

_HARD_CAP = 1000
_DEFAULT_WINDOW_DAYS = 90
# Janela de dedup: não re-raspar o mesmo perfil dentro deste intervalo. Após
# isso, perfil pode ser re-coletado (pode ter mudado de cargo/skills).
_DEDUP_WINDOW_DAYS = 180


class HiredSkillsTracker:
    def __init__(self, path: Path = HIRED_PROFILES_FILE):
        self._path = path
        self._repo = KeyedRepo("hired_profiles", "profile_url")
        self._data: dict = self._load()
        self._data.setdefault("profiles", [])

    def _load(self) -> dict:
        if is_db_enabled():
            rows = sorted(self._repo.all(), key=lambda r: r.get("scraped_at") or "")
            return {"profiles": rows}
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"Could not parse {self._path}, starting fresh")
        return {}

    def _save(self):
        files_dir.mkdir(exist_ok=True, parents=True)
        profiles = self._data.get("profiles", [])
        if len(profiles) > _HARD_CAP:
            self._data["profiles"] = profiles[-_HARD_CAP:]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self._path)

    def already_seen(
        self, profile_url: str, within_days: int = _DEDUP_WINDOW_DAYS
    ) -> bool:
        """True se o perfil foi coletado dentro de ``within_days`` (default 6 meses).

        Registros mais antigos não contam → o perfil pode ser re-raspado.
        """
        cutoff = datetime.now() - timedelta(days=within_days)
        for profile in self._data["profiles"]:
            if profile.get("profile_url") != profile_url:
                continue
            scraped_at = profile.get("scraped_at")
            if not scraped_at:
                return True
            try:
                if datetime.fromisoformat(scraped_at) >= cutoff:
                    return True
            except ValueError:
                return True
        return False

    def add_profile(
        self,
        profile_url: str,
        name: str,
        headline: str,
        company: str,
        top_skills: list[str],
        age_days: int | None,
        role: str,
        source: str = "posts",
    ) -> None:
        record = {
            "profile_url": profile_url,
            "name": name,
            "headline": headline,
            "company": company,
            "top_skills": top_skills,
            "age_days": age_days,
            "role": role,
            "source": source,
            "scraped_at": datetime.now().isoformat(),
        }
        # dedup: substitui registro existente do mesmo perfil
        self._data["profiles"] = [
            profile
            for profile in self._data["profiles"]
            if profile.get("profile_url") != profile_url
        ]
        self._data["profiles"].append(record)
        if is_db_enabled():
            self._repo.upsert(record)
        else:
            self._save()

    def _fresh(self, window_days: int) -> list[dict]:
        """Perfis dentro da janela (recência ≤ window). TTL p/ agregado atual."""
        fresh = []
        for profile in self._data["profiles"]:
            age_days = profile.get("age_days")
            if age_days is None or age_days <= window_days:
                fresh.append(profile)
        return fresh

    @staticmethod
    def _role_filter(role: str | list[str] | None) -> set[str] | None:
        """Normaliza role(s) para um set lowercased, ou None (sem filtro)."""
        if not role:
            return None
        roles = [role] if isinstance(role, str) else role
        return {r.lower() for r in roles if r}

    def aggregate(
        self,
        role: str | list[str] | None = None,
        window_days: int = _DEFAULT_WINDOW_DAYS,
    ) -> list[tuple[str, int]]:
        """Ranking skill→contagem entre contratados recentes (≤ window).

        ``role`` aceita uma string, uma lista de cargos ou None (todos).
        """
        wanted = self._role_filter(role)
        skill_counts: Counter = Counter()
        for profile in self._fresh(window_days):
            if wanted and (profile.get("role") or "").lower() not in wanted:
                continue
            for skill in profile.get("top_skills") or []:
                canonical = _canonical_skill(skill)
                if canonical:
                    skill_counts[canonical] += 1
        return skill_counts.most_common()

    def fresh_profiles(self, window_days: int = _DEFAULT_WINDOW_DAYS) -> list[dict]:
        return self._fresh(window_days)

    def _month_of(self, profile: dict) -> str | None:
        scraped_at = profile.get("scraped_at")
        if not scraped_at:
            return None
        try:
            return datetime.fromisoformat(scraped_at).strftime("%Y-%m")
        except ValueError:
            return None

    def _skill_counts_by_month(
        self, role: str | list[str] | None
    ) -> dict[str, Counter]:
        """{ 'YYYY-MM': Counter(skill->n) } a partir do mês em que cada perfil
        foi coletado (`scraped_at`). Base p/ tendência subindo/caindo."""
        wanted = self._role_filter(role)
        by_month: dict[str, Counter] = {}
        for profile in self._data["profiles"]:
            if wanted and (profile.get("role") or "").lower() not in wanted:
                continue
            month = self._month_of(profile)
            if not month:
                continue
            bucket = by_month.setdefault(month, Counter())
            for skill in profile.get("top_skills") or []:
                canonical = _canonical_skill(skill)
                if canonical:
                    bucket[canonical] += 1
        return by_month

    def trend(
        self,
        role: str | list[str] | None = None,
        recent_months: int = 1,
        prior_months: int = 2,
    ) -> list[dict]:
        """Tendência por skill: contagem na janela recente vs janela anterior.

        Agrupa por mês de coleta (`scraped_at`). Retorna lista ordenada por
        ``delta`` (recent - prior), cada item ``{skill, recent, prior, delta}``.
        Precisa de ≥2 meses de histórico p/ ter sinal.
        """
        by_month = self._skill_counts_by_month(role)
        months = sorted(by_month.keys())
        if len(months) < 2:
            return []
        recent_keys = months[-recent_months:]
        prior_keys = months[-(recent_months + prior_months) : -recent_months]
        if not prior_keys:
            prior_keys = months[:-recent_months]

        recent_counts: Counter = Counter()
        for key in recent_keys:
            recent_counts.update(by_month[key])
        prior_counts: Counter = Counter()
        for key in prior_keys:
            prior_counts.update(by_month[key])

        all_skills = set(recent_counts) | set(prior_counts)
        rows = [
            {
                "skill": skill,
                "recent": recent_counts.get(skill, 0),
                "prior": prior_counts.get(skill, 0),
                "delta": recent_counts.get(skill, 0) - prior_counts.get(skill, 0),
            }
            for skill in all_skills
        ]
        rows.sort(key=lambda row: row["delta"], reverse=True)
        return rows
