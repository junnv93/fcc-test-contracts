"""Nearest-ancestor discovery for repository-relative artifacts (SSOT).

``tests/test_repository_artifact_depth_axis.py`` names a defect class this
repository has hit three times: a module resolves a repository-relative
artifact — a file addressed from the tree root, outside its own package — by
walking a *fixed* number of directories upward from ``__file__``. That
arithmetic encodes one tree's shape and is correct in exactly the tree it was
written in. ``src/application/platform/rbac_role_catalog.py`` was correct for
months; it broke the moment a delivered package put the module one level
shallower, because ``parents[3]`` then pointed *above* the delivered tree.
Nobody edited the module — the tree changed.

``discover_tree_artifact`` is the general form of the repair that module
applied (``_discover_schema_path``): ask *where is the tree I am part of*
instead of encoding *how many directories up it is*. Deterministic — nearest
ancestor wins — and unchanged for callers already at the correct depth, since
the nearest ancestor holding the requested tree is the same answer a fixed
depth would have given, for exactly as long as that depth stays correct.

Dependency-free by contract (stdlib only) so it stays importable from the
``fcc-test-contracts`` lane, which every other lane may depend on.
"""
from __future__ import annotations

import json
import sysconfig
from importlib import resources as _resources
from pathlib import Path

__all__ = [
    'LAYOUT_RECORD_NAME',
    'PACKAGE_LAYOUT_RECORD_NAME',
    'DependencyTreeUnavailable',
    'RelocationAmbiguity',
    'discover_tree_artifact',
    'operating_repository_root',
    'resolve_dependency_artifact',
    'resolve_operating_artifact',
    'resolve_repo_artifact',
]

#: Filename the extraction packager writes into every delivered tree, recording
#: what it wrote where.
#:
#: The record is a *fact*, not a plan: ``stage_extraction_package`` already
#: knows, for each file it copies, both the repository-relative path it read and
#: the tree-relative path it wrote, and it was throwing that away. Writing it
#: down makes the packager the single source of truth about its own relocation —
#: complete by construction, because a file that was copied is a file that was
#: recorded. Every alternative (re-deriving the mapping from the manifest at
#: read time, or teaching each caller the shape of one delivered tree) puts a
#: second opinion next to the only one that actually happened.
LAYOUT_RECORD_NAME = '.extraction-layout.json'

#: The same payload, delivered *inside* the top-level package so a lane
#: installed as a wheel can still say where its own artifacts went.
#:
#: ⚠️ Deliberately a different filename, and the difference is load-bearing.
#: :func:`_tree_root` finds the box root by looking for
#: :data:`LAYOUT_RECORD_NAME`; a copy under that name inside the package makes
#: the *package directory* answer as the box root, after which every
#: repository-relative join lands one level too deep — measured 2026-08-31 as
#: four artifacts resolving to a doubled path, and, worse, as the refusal for
#: genuinely absent paths silently disappearing. Two questions, two names: the
#: box-root record says *where the box starts and what moved*; this one says
#: only *what moved*, because in a wheel there is no box.
PACKAGE_LAYOUT_RECORD_NAME = '.extraction-layout.package.json'


def discover_tree_artifact(anchor_file: str | Path, *segments: str) -> Path:
    """Resolve ``segments`` under the nearest ancestor of ``anchor_file`` that
    actually holds them, and return the joined path — not the ancestor alone.

    ``anchor_file`` must be the *caller's* ``__file__``, never this module's:
    the walk starts at the caller's own location so each tree answers for its
    own shape, whatever depth that tree happens to be delivered at.

    The existence check anchors on ``segments[0]`` — the ancestor must hold the
    *first* joined segment as a directory — not on the directory that would
    hold the final leaf. A single-segment call (``discover_tree_artifact(f,
    'scripts')``) makes that the same check as "does this ancestor hold
    itself", which every ancestor trivially satisfies at distance zero: the
    caller's own parent directory would answer immediately, joined onto itself
    a second time. Anchoring on the first segment instead of the last is what
    keeps the walk asking "where does the *named* tree start" rather than
    "does something exist here" — the question this function exists to ask.
    Multi-segment callers see the same directory checked either way, since the
    first segment's holding directory is the repository (or nearest-ancestor)
    root regardless of how many segments follow it.

    Falls back to the outermost ancestor in ``anchor_file``'s own chain (the
    true root of that chain, not a guessed depth) when no ancestor holds the
    requested tree, so a misconfigured deployment fails loudly with a named
    path instead of silently guessing — and possibly landing above the tree,
    which is exactly the 2026-08-12 failure this function replaces.

    Requires at least one segment: resolving "the tree root itself" is not
    this function's question, and silently accepting zero segments would
    return the caller's own directory for the same reason a single segment
    once did.
    """
    if not segments:
        raise ValueError('discover_tree_artifact() requires at least one segment')
    here = Path(anchor_file).resolve()
    first = segments[0]
    for ancestor in here.parents:
        if ancestor.joinpath(first).is_dir():
            return ancestor.joinpath(*segments)
    return here.parents[-1].joinpath(*segments)


def operating_repository_root() -> Path:
    """지금 **다루고 있는** 저장소의 루트 — 호출자의 cwd(또는 그 첫 조상 저장소).

    ⚠️ 위 `discover_tree_artifact` 와 **다른 질문**이다. 그쪽은 *"내가 속한 트리는
    어디인가"* 를 묻고 모듈 위치에서 파생한다. 이쪽은 *"지금 어느 저장소를 다루나"*
    를 묻는다 — 추출 도구는 자기가 사는 곳이 아니라 조작 대상 트리 위에서 파일을 센다.

    ⚠️ **모듈 위치에서 파생하면 안 된다** (2026-08-31 실측으로 배웠다). 설치된 자리에서
    `parents[1]` 은 `site-packages` 이고, 그러면 모든 경로 계산이 엉뚱한 트리를
    가리킨다 — 그리고 그 상태는 「경로가 맞다」와 **같은 모양**이다.

    ⚠️ 찾지 못하면 조용히 계속하지 않는다. 호출자들이 전부 이 뿌리 위에서 파일을
    세므로, 틀린 뿌리는 「대상이 없다」로 조용히 답한다.

    ⚠️ 이 함수가 여기 있는 이유: 이것을 필요로 하는 모듈이 둘 이상이고(추출 계획기 ·
    경계 검사기) 열두 줄을 복사하면 그 사본이 갈라진다. 위 §머리말이 이름 붙인 결함
    계급과 같은 것이다 — 같은 사실이 두 곳에 있고 하나가 먼저 낡는다.
    """
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / 'pyproject.toml').is_file() and (candidate / '.git').exists():
            return candidate
    raise RuntimeError(
        f'대상 저장소를 찾지 못했다 (cwd={here}) — 이 도구는 저장소 안에서 실행해야 '
        '한다. 모듈이 사는 곳이 아니라 **다루는 곳**이 기준이다.'
    )


class DependencyTreeUnavailable(LookupError):
    """This module has no tree to answer for, so a dependency artifact cannot be found.

    Distinct from :class:`RelocationAmbiguity`, which means *the record gave two
    answers*. This one means *there is no record and no checkout* — the shape an
    installed wheel produces. Both are refusals rather than guesses, for the same
    reason: a resolver that answers anyway hands back a path that looks
    authoritative and is wrong.
    """


class RelocationAmbiguity(LookupError):
    """A requested directory was split across more than one delivered location.

    Raised rather than resolved, because every way of choosing between the
    candidates is a guess, and a guessing resolver reintroduces exactly the
    silence this module exists to end: the caller would receive a path that
    looks authoritative and is wrong for some of the files under it.
    """


def resolve_repo_artifact(anchor_file: str | Path, rel_path: str) -> Path:
    """Where ``rel_path`` — a *repository-relative* path — lives in this tree.

    Callers name artifacts the way the repository names them
    (``'docs/platform/migrations'``), which is the vocabulary every test, doc
    and ledger entry already uses. What changes between trees is not the name
    but the location: the extraction packager delivers
    ``docs/platform/migrations/001_x.sql`` as ``migrations/001_x.sql`` and
    ``src/application/platform/rbac_role_catalog.py`` as
    ``fcc_test_platform/application/rbac_role_catalog.py``.

    In the monorepo there is no layout record and the answer is the joined path
    itself — **byte-identical to what a caller computed before**, which is why
    adopting this function cannot move the monorepo suite. In a delivered tree
    the record answers, and it answers from what the packager did rather than
    from anyone's model of what it should have done.

    Directory moves are *derived* from the file records rather than declared a
    second time: for ``docs/platform/migrations`` the resolver looks at every
    recorded file beneath it whose delivered path still ends with the same
    tail, and takes the directory those tails hang from. Files the packager
    also *renamed* (``platform_ingestion.py`` → ``provider_ingestion.py``) carry
    no directory evidence and are excluded from that inference — they can only
    be addressed by their exact path, which is the honest consequence of a
    rename.

    An unrecorded path resolves to itself. That is not a silent success: the
    caller gets the same missing path it would have got anyway, and fails
    naming it, which is strictly more informative than this function inventing
    a location for a file the box does not contain.
    """
    return _resolve_under(
        _tree_root(Path(anchor_file).resolve()), rel_path, 'resolve_repo_artifact',
    )


def resolve_operating_artifact(rel_path: str) -> Path:
    """Where ``rel_path`` lives in the repository being **operated on**.

    The third question this module answers, and it is not a variant of the
    other two. :func:`resolve_repo_artifact` asks *where did my own tree put
    this* and :func:`resolve_dependency_artifact` asks *where did the tree that
    delivered me put this*; both derive from a module's location. A tool that
    reads one repository while living in another needs neither — see
    :func:`operating_repository_root` for why the extraction tooling counts
    files on the tree it is pointed at rather than the tree it was installed
    from.

    ⚠️ Anchoring such a tool on its own ``__file__`` is wrong in a way that
    looks right, which is why it survived. Installed inside a consumer's
    checkout the module sits under ``<consumer>/venv/lib/.../site-packages``,
    so :func:`_tree_root` walks *out of the virtualenv* and finds the
    consumer's own ``pyproject.toml`` — and then answers with the consumer's
    path, which is the correct answer by accident, for the wrong reason. Move
    the same install one directory outside any checkout and the identical call
    walks to the filesystem root and answers ``/docs/api/...``. Measured
    2026-09-05: the same commit, two rigs, two different failures, and only one
    of them visible to anyone running the tool from inside the monorepo.

    The relocation record is still consulted, so a delivered box that was asked
    to operate on itself resolves through what its packager actually wrote.
    """
    return _resolve_under(
        operating_repository_root(), rel_path, 'resolve_operating_artifact',
    )


def _resolve_under(root: Path, rel_path: str, caller: str) -> Path:
    """``rel_path`` under ``root``, through ``root``'s relocation record if it has one.

    The join is shared rather than spelled once per question because *which
    tree* and *where in a tree* are separate decisions: each public resolver
    answers the first, and there is only ever one answer to the second.
    """
    rel = str(rel_path).replace('\\', '/').strip('/')
    if not rel:
        raise ValueError(f'{caller}() requires a repository-relative path')
    record = _layout_record(root)
    if not record:
        return root.joinpath(*rel.split('/'))
    delivered = record.get(rel, _delivered_directory(rel, record))
    # A tree whose files landed at its own root answers with the root itself.
    return root.joinpath(*delivered.split('/')) if delivered else root


def resolve_dependency_artifact(rel_path: str) -> Path:
    """Where ``rel_path`` lives in **the tree that delivered this module**.

    :func:`resolve_repo_artifact` answers *where did my own tree put this*, and
    for an artifact a lane owns that is the whole question. It is the wrong
    question for an artifact a *dependency* owns: the platform box's tests read
    ``docs/api/platform-api.openapi.json``, a file the contracts lane owns and
    ships in its own box as ``artifacts/platform-api.openapi.json``. Anchored on
    the caller, the resolver correctly reports that the platform tree does not
    contain it and hands back the path unchanged — which is honest, and still a
    failure.

    Anchoring on *this module* instead changes which tree is asked, and nothing
    else. This module belongs to the dependency-free lane every other lane
    depends on, so wherever it was imported from is, by construction, the
    delivered tree of that dependency:

    * In the monorepo it resolves from ``src/application/common/``, there is no
      layout record above it, and the answer is the joined repository-relative
      path — **identical** to what the caller computed before. That identity is
      what keeps the monorepo suite byte-for-byte unchanged.
    * In a delivered box that received this lane as an installed requirement,
      ``__file__`` points into that lane's tree, whose record says where the
      artifact landed.

    No package name appears here, and no manifest key was added. The question is
    not *which sibling holds this* — that would need a table, and a table is a
    second opinion next to the packager's own record. The question is *where did
    the tree I came from put it*, which the record already answers.

    The precondition — that the dependency-free lane is the only extraction
    target any other target depends on — is not assumed silently: the packaging
    axis asserts it as a derivation over the manifest, so a second sibling target
    turns red here rather than resolving to the wrong tree.

    **Raises rather than guesses when this module has no tree.** Installed as a
    wheel into ``site-packages``, this module sits under neither a layout record
    nor a repository checkout, and :func:`_tree_root` then falls through to the
    filesystem anchor — after which joining a repository-relative path yields
    ``/docs/api/...``, a location nothing put anything at. That is precisely the
    invention :class:`RelocationAmbiguity` exists to refuse, so it is refused
    here too: the artifacts a lane ships at its *box root* (``artifacts/``) are
    outside the importable package and do not travel inside a wheel, and the
    honest answer to "where did my dependency put this" in that shape is that
    the question cannot be answered, not a path that looks authoritative.
    """
    here = Path(__file__).resolve()
    root = _tree_root(here)
    # ⚠️ **A consumer's project root is not this lane's tree.** :func:`_tree_root`
    # falls back to the nearest ancestor holding ``.git`` or ``pyproject.toml``,
    # and a provider installs this lane into a virtualenv **inside their own
    # project** — so that walk finds the *consumer's* ``pyproject.toml`` and every
    # repository-relative join then lands under the consumer, at a path nothing
    # put anything at. The refusal below never fired, because it only asks whether
    # the walk reached the filesystem root.
    #
    # Measured 2026-09-04, reported by a provider lane and reproduced minimally:
    # a project holding ``pyproject.toml`` with ``venv/`` inside it resolved the
    # SSOT contract to ``<consumer>/fcc_test_contracts/artifacts/…`` and returned
    # it **without raising**. That is exactly the invention this module exists to
    # refuse — *"a path that looks authoritative and is wrong"* — living in its own
    # fallback.
    #
    # The discriminator is *where this module was read from*, not what sits above
    # it: a module under an installation directory was installed, so there is no
    # delivering checkout above it and only the packaged copy can answer. An
    # editable install keeps the module in the source tree and is unaffected.
    if root == root.parent or _is_installed_location(here):
        packaged = _packaged_artifact(rel_path)
        if packaged is not None:
            return packaged
        raise DependencyTreeUnavailable(
            f'cannot resolve {rel_path!r} through the tree that delivered '
            f'{__name__}: this module resolves to {__file__!r}, which sits under '
            'neither a delivered box (no layout record above it) nor a repository '
            'checkout. A lane installed as a wheel carries its importable '
            'packages, not the artifacts it ships at its box root, and no copy '
            'of this path was delivered inside the package either — deliver the '
            'sibling as a tree on sys.path, or ship the artifact as package data.'
        )
    return resolve_repo_artifact(__file__, rel_path)


def _is_installed_location(here: Path) -> bool:
    """Was this module read from an installation directory rather than a checkout?

    Two questions, because neither alone covers the shapes this lane ships into:
    the running interpreter's own ``purelib``/``platlib`` answer for the
    environment executing right now, and the ``site-packages`` /
    ``dist-packages`` path component answers for an environment some *other*
    interpreter created (a provider's ``venv/`` invoked by path, a bundled
    runtime), which ``sysconfig`` does not describe.

    Deliberately **not** a check for "is there a checkout above me": that is the
    question that fails, because a consumer project is a checkout and it is not
    this lane's.
    """
    if any(part in {'site-packages', 'dist-packages'} for part in here.parts):
        return True
    paths = sysconfig.get_paths()
    for key in ('purelib', 'platlib'):
        location = paths.get(key)
        if location and here.is_relative_to(Path(location).resolve()):
            return True
    return False


def _packaged_artifact(rel_path: str) -> Path | None:
    """Where ``rel_path`` landed *inside* this module's own package, if it did.

    A wheel carries the importable package and nothing else. The box-root
    layout record and the box-root ``artifacts/`` directory are both outside
    it, so a lane installed as a requirement can answer nothing about its own
    relocation — which is a true statement about a real delivery shape, and
    was refusing consumers that the lane genuinely ships for.

    The repair keeps the same authority: the packager writes its record into
    the top-level package as well as the box root, so an installed lane reads
    *the packager's own account* of where a file went rather than inferring
    one from a naming convention. Only paths delivered inside the package are
    answerable here — a path recorded as landing at the box root returns
    ``None`` and the caller refuses, exactly as before, because a wheel really
    does not contain it.

    Resolved through :mod:`importlib.resources` rather than by walking up from
    ``__file__``, for the reason the migration discovery SSOT gives: a frozen
    or zipped distribution has no directory to walk.
    """
    package = __name__.split('.')[0]
    try:
        anchor = _resources.files(package)
        record_text = anchor.joinpath(PACKAGE_LAYOUT_RECORD_NAME).read_text(encoding='utf-8')
    except (ModuleNotFoundError, FileNotFoundError, OSError, TypeError):
        return None
    record = dict((json.loads(record_text).get('paths') or {}))
    rel = str(rel_path).replace('\\', '/').strip('/')
    delivered = record.get(rel, _delivered_directory(rel, record))
    prefix = package + '/'
    if not delivered.startswith(prefix):
        # Delivered outside the importable package: a wheel does not carry it,
        # and naming a path here would invent one.
        return None
    # ⚠️ ``anchor`` is a Traversable, and for a namespace package it is a
    # ``MultiplexedPath`` whose ``str()`` is a repr, not a path — building a
    # ``Path`` from it yields a location nothing is at, and every lookup then
    # fails as *absent* rather than as *misresolved*. Derive the package
    # directory from this module's own dotted name instead: the number of
    # dots is how far ``__file__`` sits below its top-level package, which is
    # a fact about this module rather than about any tree it ships in.
    package_dir = Path(__file__).resolve().parents[__name__.count('.') - 1]
    candidate = package_dir.joinpath(*delivered[len(prefix):].split('/'))
    return candidate if candidate.exists() else None


def _tree_root(here: Path) -> Path:
    """Nearest ancestor holding a layout record, else the repository root.

    The fallback asks the same question :func:`discover_tree_artifact` asks —
    *where does the tree I am part of start* — using the markers a checkout of
    this repository has. It is only reachable for a tree the packager did not
    write, so a delivered box that later grows its own ``pyproject.toml`` (the
    packaging axis this repository has not yet decided) still resolves through
    its record, which is checked first.
    """
    for ancestor in here.parents:
        if (ancestor / LAYOUT_RECORD_NAME).is_file():
            return ancestor
    for ancestor in here.parents:
        if (ancestor / '.git').exists() or (ancestor / 'pyproject.toml').is_file():
            return ancestor
    return here.parents[-1]


def _layout_record(root: Path) -> dict[str, str]:
    path = root / LAYOUT_RECORD_NAME
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding='utf-8'))
    return dict(payload.get('paths') or {})


def _delivered_directory(rel: str, record: dict[str, str]) -> str:
    prefix = rel + '/'
    candidates: set[str] = set()
    for current, future in record.items():
        if not current.startswith(prefix):
            continue
        tail = current[len(prefix):]
        if future == tail:
            candidates.add('')
        elif future.endswith('/' + tail):
            candidates.add(future[: -len(tail) - 1])
    if len(candidates) > 1:
        # The tree root is a legitimate destination and renders as the empty
        # string, which reads as nothing at all in the one message a reader
        # gets. Name it.
        named = sorted(candidate or '<tree root>' for candidate in candidates)
        raise RelocationAmbiguity(
            f'{rel!r} was delivered to more than one location: '
            f'{named!r} — address the files individually'
        )
    return candidates.pop() if candidates else rel

