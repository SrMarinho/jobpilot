"""Executa um job da fila: worktree isolado, gates, commit, push.

O ponto mais delicado do sistema. O que o mantém aceitável:

**Ordem dos gates.** A verificação de caminhos vem **antes** de rodar
qualquer coisa, porque ``pytest`` importa o código do patch — importar é
executar. Conferir depois seria conferir depois do fato.

**Base é ``origin/master``, nunca o HEAD local.** O repositório de trabalho tem
arquivos não comitados a qualquer momento (hoje mesmo há um
``resume_variants.py`` untracked); herdar working tree faria o patch carregar
trabalho alheio pro commit.

**O agente não tem shell.** ``claude -p`` roda sem Bash, WebFetch e WebSearch:
não roda git, não instala dependência, não sai pra rede. Todo git é feito aqui,
em Python, com argv fixo — nunca string de shell com texto de LLM interpolado.

**``.env`` não entra no worktree.** O ``conftest.py`` já zera ``DATABASE_URL``
e o CI roda sem ``.env``, então os gates passam sem ele. Copiar seria entregar
segredos e a URL de produção ao agente.

**Telegram em toda tentativa**, sucesso ou falha. Silêncio não é um estado
possível: um sistema que altera código sozinho e não conta não é autônomo, é
solto.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from src.config.env import env_int
from src.config.settings import files_dir, logger
from src.core.persistence.doc_repo import DocRepo
from src.core.use_cases.evolve import patch_policy as policy
from src.core.use_cases.evolve.evolve_state import EvolveState
from src.core.use_cases.evolve.queue import (
    KIND_PROMOTE_SELECTOR,
    EvolutionQueue,
    Job,
)

REPO_ROOT = Path("").resolve()
WORKTREE_DIR = REPO_ROOT / ".local" / "evolve"
PATCHES_DIR = files_dir / "evolution_patches"

PATCH_TIMEOUT_S = env_int("EVOLVE_PATCH_TIMEOUT_S", 420)
GATE_TIMEOUT_S = env_int("EVOLVE_GATE_TIMEOUT_S", 300)


#: Só faz push com isto ligado. Default desligado: escrever no remoto é
#: irreversível o suficiente pra exigir intenção explícita.
def push_enabled() -> bool:
    return os.getenv("EVOLVE_PUSH", "false").strip().lower() in {"1", "true", "yes"}


def evolve_enabled() -> bool:
    return os.getenv("EVOLVE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def patch_model() -> str:
    return os.getenv("EVOLVE_PATCH_MODEL", "claude-sonnet-5")


@dataclass(slots=True)
class Step:
    name: str
    ok: bool
    detail: str = ""


@dataclass(slots=True)
class PatchResult:
    job_id: str
    kind: str
    ok: bool
    branch: str = ""
    reason: str = ""
    steps: list[Step] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    diff: str = ""
    usd: float = 0.0
    pushed: bool = False

    def add(self, name: str, ok: bool, detail: str = "") -> Step:
        step = Step(name, ok, detail)
        self.steps.append(step)
        level = logger.info if ok else logger.warning
        level(f"[evolve] gate {name}: {'ok' if ok else 'FALHOU'} {detail}".strip())
        return step


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Subprocess com argv em lista — nunca shell."""
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        shell=False,
    )


def _git(args: list[str], *, cwd: Path | None = None, timeout: int = 120):
    return _run(["git", *args], cwd=cwd or REPO_ROOT, timeout=timeout)


def open_evolve_branches() -> list[str]:
    """Branches ``evolve/*`` no remoto, ainda não removidas."""
    result = _git(["branch", "-r", "--list", "origin/evolve/*"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def prune_worktrees() -> None:
    """Remove worktree órfão antes de começar.

    O Agendador pode cortar o drain no meio (``ExecutionTimeLimit``), e aí o
    worktree fica pra trás. Limpar no início é o que impede o diretório de
    acumular restos de execuções mortas.
    """
    _git(["worktree", "prune"])
    if not WORKTREE_DIR.exists():
        return
    for path in WORKTREE_DIR.iterdir():
        if path.is_dir() and path.name.startswith("wt-"):
            _git(["worktree", "remove", "--force", str(path)])
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)


class Patcher:
    def __init__(
        self,
        queue: EvolutionQueue | None = None,
        state: EvolveState | None = None,
        *,
        dry_run: bool = False,
    ):
        self.queue = queue or EvolutionQueue()
        self.state = state or EvolveState()
        self.dry_run = dry_run

    # ── entrada ─────────────────────────────────────────────────────────────
    def drain_one(self) -> PatchResult | None:
        """Executa no máximo um job. ``None`` quando não há o que fazer."""
        prune_worktrees()

        job = self.queue.next_job()
        if job is None:
            logger.info("[evolve] fila vazia")
            return None

        verdict = policy.check_budget(
            **_budget_kwargs(self.state), enabled=evolve_enabled()
        )
        if not verdict:
            logger.info(f"[evolve] patch não autorizado: {verdict.reason}")
            return PatchResult(job.id, job.kind, False, reason=verdict.reason)

        base_sha = self._fetch_base()
        if base_sha is None:
            return PatchResult(
                job.id, job.kind, False, reason="não consegui ler origin/master"
            )

        if self.state.already_attempted(job.sig, base_sha):
            # Anti-loop: mesmo problema, mesmo código, uma tentativa só.
            self.queue.mark_done(job.id, note="já tentado sobre este commit")
            logger.info(f"[evolve] job {job.id} já tentado sobre {base_sha[:8]}")
            return None

        return self._execute(job, base_sha)

    # ── execução ────────────────────────────────────────────────────────────
    def _fetch_base(self) -> str | None:
        fetch = _git(["fetch", "origin", "master"])
        if fetch.returncode != 0:
            logger.warning(f"[evolve] git fetch falhou: {fetch.stderr[:200]}")
            return None
        rev = _git(["rev-parse", "origin/master"])
        if rev.returncode != 0:
            return None
        return rev.stdout.strip()

    def _execute(self, job: Job, base_sha: str) -> PatchResult:
        subject = job.payload.get("field") or job.kind
        branch = policy.branch_name(
            job.kind, subject, day=date.today().strftime("%Y%m%d")
        )
        result = PatchResult(job.id, job.kind, False, branch=branch)
        worktree = WORKTREE_DIR / f"wt-{job.id}"

        self.queue.mark_running(job.id, base_sha=base_sha)
        self.state.record_attempt(job.sig, base_sha)

        try:
            if not self._add_worktree(worktree, branch, base_sha, result):
                return self._finish(job, result)

            if not self._apply_change(job, worktree, result):
                return self._finish(job, result)

            if not self._gates(worktree, result):
                return self._finish(job, result)

            self._commit_and_push(job, worktree, branch, result, subject=subject)
            result.ok = True
            return self._finish(job, result)
        except subprocess.TimeoutExpired as e:
            result.add("timeout", False, f"{e.cmd[:1]} passou de {e.timeout}s")
            result.reason = "timeout"
            return self._finish(job, result)
        except Exception as e:
            result.add("erro", False, f"{type(e).__name__}: {e}")
            result.reason = str(e)[:300]
            return self._finish(job, result)
        finally:
            self._cleanup(worktree, result)

    def _add_worktree(
        self, worktree: Path, branch: str, base_sha: str, result: PatchResult
    ) -> bool:
        WORKTREE_DIR.mkdir(parents=True, exist_ok=True)
        # Base é origin/master: o working tree local tem arquivos não comitados
        # e herdá-los levaria trabalho alheio pro commit.
        add = _git(
            ["worktree", "add", "-b", branch, str(worktree), base_sha], timeout=180
        )
        ok = add.returncode == 0
        result.add("worktree", ok, "" if ok else add.stderr[:200])
        return ok

    def _apply_change(self, job: Job, worktree: Path, result: PatchResult) -> bool:
        """Edição mecânica quando dá; ``claude -p`` quando não dá."""
        if job.kind == KIND_PROMOTE_SELECTOR:
            if self._promote_mechanically(job, worktree, result):
                return True
            logger.info("[evolve] promoção mecânica não deu — caindo pro agente")
        return self._run_agent(job, worktree, result)

    def _promote_mechanically(
        self, job: Job, worktree: Path, result: PatchResult
    ) -> bool:
        from src.core.use_cases.evolve.constant_editor import (
            insert_candidate,
            promotion_note,
        )
        from src.core.use_cases.evolve.selector_registry import spec_for

        field_name = job.payload.get("field", "")
        selector = job.payload.get("selector", "")
        spec = spec_for(field_name)
        if spec is None or not selector:
            result.add("promoção mecânica", False, "campo sem spec ou selector vazio")
            return False

        relativo = spec.module.replace(".", "/") + ".py"
        alvo = worktree / relativo
        if not alvo.exists():
            result.add("promoção mecânica", False, f"arquivo ausente: {relativo}")
            return False

        editado = insert_candidate(
            alvo.read_text(encoding="utf-8"),
            spec.constant,
            selector,
            note=promotion_note(day=date.today().isoformat()),
        )
        if not editado:
            result.add("promoção mecânica", False, editado.reason)
            return False

        alvo.write_text(editado.content, encoding="utf-8")
        result.add("promoção mecânica", True, f"{relativo}:{spec.constant}")
        return True

    def _run_agent(self, job: Job, worktree: Path, result: PatchResult) -> bool:
        if self.dry_run:
            result.add("agente", False, "dry-run: agente não foi chamado")
            return False

        mission = job.payload.get("mission")
        if not mission:
            result.add("agente", False, "job sem missão declarada")
            return False

        args = [
            "claude",
            "-p",
            mission,
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            *policy.ALLOWED_TOOLS,
            "--disallowedTools",
            *policy.DISALLOWED_TOOLS,
            "--model",
            patch_model(),
            "--output-format",
            "json",
            "--max-turns",
            str(env_int("EVOLVE_PATCH_MAX_TURNS", 24)),
        ]
        proc = _run(
            args,
            cwd=worktree,
            timeout=PATCH_TIMEOUT_S,
            env=policy.child_env(dict(os.environ)),
        )
        result.usd = _cost_of(proc.stdout)
        ok = proc.returncode == 0
        result.add(
            "agente",
            ok,
            f"custo US$ {result.usd:.4f}" if ok else proc.stderr[:200],
        )
        return ok

    def _gates(self, worktree: Path, result: PatchResult) -> bool:
        """Caminhos primeiro. Só depois executa qualquer coisa."""
        # `--ignored=matching -uall` é obrigatório, não zelo: sem isso o
        # `git status --porcelain` ESCONDE arquivo que está no .gitignore, e
        # `.env` está lá. Um agente que escrevesse `.env` passava invisível
        # pelo gate de caminhos — verificado na prática antes de este
        # argumento existir. O gate precisa ver tudo que o agente tocou, não
        # só o que o git pretende comitar.
        status = _git(
            ["status", "--porcelain", "--ignored=matching", "-uall"], cwd=worktree
        )
        if status.returncode != 0:
            result.add("diff", False, status.stderr[:200])
            return False

        paths = _changed_paths(status.stdout)
        result.files = paths
        linhas = _diff_lines(worktree)
        result.diff = _diff_text(worktree)

        verdict = policy.check_diff(paths, changed_lines=linhas)
        result.add(
            "caminhos", bool(verdict), verdict.reason or f"{len(paths)} arquivo(s)"
        )
        if not verdict:
            result.reason = verdict.reason
            return False

        env = policy.child_env(dict(os.environ))
        for nome, args in (
            ("ruff check", ["uv", "run", "ruff", "check"]),
            ("ruff format", ["uv", "run", "ruff", "format", "--check"]),
            ("pytest", ["uv", "run", "pytest", "-q"]),
        ):
            proc = _run(args, cwd=worktree, timeout=GATE_TIMEOUT_S, env=env)
            ok = proc.returncode == 0
            saida = (proc.stdout or proc.stderr)[-400:]
            result.add(nome, ok, "" if ok else saida)
            if not ok:
                result.reason = f"{nome} reprovou"
                return False

        return self._smoke(worktree, result, env)

    def _smoke(self, worktree: Path, result: PatchResult, env: dict) -> bool:
        """Integridade de import e fiação do CLI — o que ruff e pytest não veem.

        Sem browser de propósito: o drain roda sem browser, e pedir o lock aqui
        colocaria o patch na fila atrás dos runs agendados.
        """
        checagens = (
            (
                "import do router",
                [
                    "uv",
                    "run",
                    "python",
                    "-c",
                    "from src.interfaces.cli.router import register",
                ],
            ),
            ("cli --help", ["uv", "run", "python", "main.py", "--help"]),
            (
                "canary --help",
                [
                    "uv",
                    "run",
                    "python",
                    "main.py",
                    "config",
                    "selectors-check",
                    "--help",
                ],
            ),
        )
        for nome, args in checagens:
            proc = _run(args, cwd=worktree, timeout=120, env=env)
            ok = proc.returncode == 0
            result.add(f"smoke: {nome}", ok, "" if ok else (proc.stderr or "")[-300:])
            if not ok:
                result.reason = f"smoke falhou em {nome}"
                return False
        return True

    def _commit_and_push(
        self,
        job: Job,
        worktree: Path,
        branch: str,
        result: PatchResult,
        *,
        subject: str,
    ) -> None:
        from src.core.use_cases.evolve.patch_mission import build_commit_message

        mensagem = build_commit_message(
            kind=job.kind,
            subject=job.payload.get("commit_subject") or f"atualiza {subject}",
            body=job.payload.get("commit_body") or "Correção automática do evolve.",
            sig=job.sig,
        )
        _git(["add", "-A"], cwd=worktree)
        env_commit = {
            **os.environ,
            "GIT_AUTHOR_NAME": "jobpilot-evolve",
            "GIT_AUTHOR_EMAIL": "evolve@jobpilot.local",
            "GIT_COMMITTER_NAME": "jobpilot-evolve",
            "GIT_COMMITTER_EMAIL": "evolve@jobpilot.local",
        }
        # --no-verify não entra aqui: os hooks são ruff check + format, e eles
        # já passaram nos gates. Se falharem, é sinal de que algo divergiu.
        commit = _run(
            ["git", "commit", "-m", mensagem],
            cwd=worktree,
            timeout=120,
            env=env_commit,
        )
        ok = commit.returncode == 0
        result.add("commit", ok, "" if ok else (commit.stdout or commit.stderr)[-300:])
        if not ok:
            result.reason = "commit falhou"
            return

        if not push_enabled():
            result.add("push", True, "desligado (EVOLVE_PUSH=false)")
            return
        if not policy.is_pushable(branch):
            # Trava de dentro. A de fora é branch protection no GitHub.
            result.add("push", False, f"branch fora de evolve/*: {branch}")
            result.reason = "branch não empurrável"
            return

        push = _git(["push", "-u", "origin", branch], cwd=worktree, timeout=180)
        result.pushed = push.returncode == 0
        result.add("push", result.pushed, "" if result.pushed else push.stderr[:200])

    # ── encerramento ────────────────────────────────────────────────────────
    def _finish(self, job: Job, result: PatchResult) -> PatchResult:
        self.state.record_patch(usd=result.usd)
        if result.ok:
            self.queue.mark_done(job.id)
            self.state.record_gate_success()
            self._mark_incident(job, resolved=True)
        else:
            self.queue.mark_failed(job.id, result.reason or "falha sem motivo")
            self.state.record_gate_failure()
        _save_patch_doc(job, result)
        self._notify(job, result)
        return result

    def _mark_incident(self, job: Job, *, resolved: bool) -> None:
        if not job.sig:
            return
        try:
            from src.core.use_cases.evolve.incident_store import (
                STATUS_RESOLVED,
                IncidentStore,
            )

            IncidentStore().set_status(
                job.sig,
                STATUS_RESOLVED,
                note=f"patch {job.id} ({job.kind})",
            )
        except Exception as e:
            logger.warning(f"[evolve] não marquei o incidente: {e}")

    def _cleanup(self, worktree: Path, result: PatchResult) -> None:
        """Sempre remove — o diff já foi persistido antes."""
        if (
            os.getenv("EVOLVE_KEEP_FAILED", "").lower() in {"1", "true"}
            and not result.ok
        ):
            logger.info(f"[evolve] worktree preservado para inspeção: {worktree}")
            return
        if worktree.exists():
            _git(["worktree", "remove", "--force", str(worktree)])
            if worktree.exists():
                shutil.rmtree(worktree, ignore_errors=True)
        _git(["worktree", "prune"])

    def _notify(self, job: Job, result: PatchResult) -> None:
        try:
            from src.utils.telegram import send_telegram

            send_telegram(_telegram_text(job, result), topic="alerts")
        except Exception as e:
            logger.warning(f"[evolve] falha ao notificar patch: {e}")


# ── helpers puros ───────────────────────────────────────────────────────────
def _budget_kwargs(state: EvolveState) -> dict:
    snap = state.snapshot()
    return {
        "patches_today": snap.patches_today,
        "patches_week": snap.patches_week,
        "usd_today": snap.usd_today,
        "open_branches": len(open_evolve_branches()),
        "paused": snap.paused,
        "in_cooldown": snap.in_cooldown,
    }


def _changed_paths(porcelain: str) -> list[str]:
    """Caminhos de ``git status --porcelain``, incluindo renomeados."""
    paths: list[str] = []
    for linha in porcelain.splitlines():
        if len(linha) < 4:
            continue
        resto = linha[3:].strip()
        if " -> " in resto:
            # Renomeado: o que importa é o destino.
            resto = resto.split(" -> ", 1)[1]
        paths.append(resto.strip('"'))
    return paths


def _diff_lines(worktree: Path) -> int:
    proc = _git(["diff", "--numstat", "HEAD"], cwd=worktree)
    total = 0
    for linha in proc.stdout.splitlines():
        partes = linha.split("\t")
        if len(partes) >= 2:
            for valor in partes[:2]:
                if valor.isdigit():
                    total += int(valor)
    return total


def _diff_text(worktree: Path, limit: int = 6000) -> str:
    proc = _git(["diff", "HEAD"], cwd=worktree)
    return proc.stdout[:limit]


def _cost_of(stdout: str) -> float:
    """Custo em USD do JSON do ``claude -p``. Zero quando não dá pra ler."""
    try:
        data = json.loads(stdout)
    except Exception:
        return 0.0
    if isinstance(data, dict):
        for chave in ("total_cost_usd", "cost_usd"):
            if chave in data:
                try:
                    return float(data[chave])
                except (TypeError, ValueError):
                    return 0.0
    return 0.0


def _save_patch_doc(job: Job, result: PatchResult) -> None:
    """Persiste a tentativa antes de o worktree ser removido.

    Falha que não deixa rastro é falha que ninguém diagnostica — e o worktree,
    onde estaria o diff, é apagado logo em seguida.
    """
    try:
        repo = DocRepo("evolution_patches", json_dir=PATCHES_DIR)
        repo.put(
            job.id,
            {
                "job": job.as_doc(),
                "ok": result.ok,
                "branch": result.branch,
                "reason": result.reason,
                "files": result.files,
                "diff": result.diff,
                "usd": result.usd,
                "pushed": result.pushed,
                "steps": [
                    {"name": s.name, "ok": s.ok, "detail": s.detail}
                    for s in result.steps
                ],
                "at": datetime.now().isoformat(timespec="seconds"),
            },
        )
    except Exception as e:
        logger.warning(f"[evolve] não consegui gravar o histórico do patch: {e}")


def _telegram_text(job: Job, result: PatchResult) -> str:
    import html

    icone = "✅" if result.ok else "❌"
    passos = "\n".join(
        f"{'✓' if s.ok else '✗'} {html.escape(s.name)}"
        + (f" — <i>{html.escape(s.detail[:120])}</i>" if s.detail and not s.ok else "")
        for s in result.steps
    )
    arquivos = "\n".join(f"• <code>{html.escape(f)}</code>" for f in result.files)
    rodape = (
        f"\n\nBranch: <code>{html.escape(result.branch)}</code>"
        + ("  (empurrada)" if result.pushed else "  (local)")
        if result.branch
        else ""
    )
    motivo = (
        f"\n\n<b>Motivo:</b> {html.escape(result.reason[:200])}"
        if result.reason and not result.ok
        else ""
    )
    return (
        f"{icone} <b>Patch do evolve</b> — {html.escape(job.kind)}\n"
        f"Job <code>{job.id}</code> · US$ {result.usd:.4f}\n\n"
        f"{passos}{motivo}\n\n{arquivos}{rodape}"
    )
