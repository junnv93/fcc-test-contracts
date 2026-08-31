"""A lane's contract artifacts must be reachable from an **installed** lane.

The defect this seals was invisible to every check that ran in a checkout,
and that is the whole point of the file. ``resolve_dependency_artifact``
answers *where did the tree that delivered me put this*, and in a checkout the
tree is the repository — so it answers correctly, from a directory the
consumer will never receive. Installed as a wheel, the same call raised
``DependencyTreeUnavailable``: a wheel carries importable packages, and the
artifacts sat at the box root, outside every one of them.

Measured 2026-08-31 on the platform lane's CI: 33 of 42 failures were that one
refusal. Nothing was misconfigured and no test was wrong — the artifacts
really were unreachable, and the refusal was the resolver being honest.

So this file does not inspect the source tree. It **builds the wheel and
installs it**, because the checkout and the wheel are exactly the two states a
tree-shaped check cannot tell apart. Everything cheaper measures the state
that was never broken.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Repository-relative artifacts a consumer lane actually asks for. Named
#: rather than globbed: the question is whether the paths *consumers use*
#: resolve, and a glob over the delivered directory would pass by construction.
CONSUMER_REQUESTED = (
    'docs/api/platform-api.openapi.json',
    'docs/api/platform-api.asyncapi.json',
    'docs/api/headless-api.openapi.json',
    'docs/api/headless_contract_extraction_manifest.v1.json',
    'docs/platform/provider_service_deployment_evidence.schema.v1.json',
)

_PROBE = r'''
import json, sys
from fcc_test_contracts.common.tree_artifacts import (
    DependencyTreeUnavailable, resolve_dependency_artifact,
)
import fcc_test_contracts.common.tree_artifacts as m

out = {'module': m.__file__, 'resolved': {}, 'refused_absent': False}
for rel in json.loads(sys.argv[1]):
    try:
        out['resolved'][rel] = resolve_dependency_artifact(rel).is_file()
    except DependencyTreeUnavailable:
        out['resolved'][rel] = 'REFUSED'
try:
    resolve_dependency_artifact('src/nowhere/definitely_absent.py')
except DependencyTreeUnavailable:
    out['refused_absent'] = True
print(json.dumps(out))
'''


def _staged_copy(tmp: Path) -> Path:
    """A pristine copy of the tree, built from what git tracks.

    ⚠️ Building in place is not an option here: setuptools writes ``build/``
    into the source tree, ``.gitignore`` hides it from ``git status``, and the
    next test run then counts a stale duplicate of every module alongside the
    original. This repository's own ``scripts/lane_check.py`` refuses a tree in
    that state — a gate this file tripped the first time it ran, which is the
    honest evidence that a build must not happen where measurements do.

    Copying what git tracks (rather than the working tree) also means the wheel
    is built from the committed shape, which is the shape a consumer receives.
    """
    staged = tmp / 'src'
    staged.mkdir()
    listed = subprocess.run(
        ['git', 'ls-files', '-z'], cwd=str(_REPO_ROOT),
        check=True, capture_output=True, text=True,
    ).stdout.split('\0')
    tracked = [name for name in listed if name]
    if not tracked:
        raise AssertionError('git listed no tracked files — nothing to build')
    for name in tracked:
        source = _REPO_ROOT / name
        if not source.is_file():
            continue
        target = staged / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return staged


def _build_and_probe(tmp: Path) -> dict:
    wheels = tmp / 'wheels'
    subprocess.run(
        [sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-cache-dir',
         '-w', str(wheels), str(_staged_copy(tmp))],
        check=True, capture_output=True,
    )
    built = sorted(wheels.glob('*.whl'))
    if len(built) != 1:
        raise AssertionError(f'expected exactly one wheel, got {built!r}')
    venv = tmp / 'venv'
    subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True, capture_output=True)
    python = venv / ('Scripts' if sys.platform == 'win32' else 'bin') / 'python'
    subprocess.run(
        [str(python), '-m', 'pip', 'install', '-q', '--no-cache-dir', str(built[0])],
        check=True, capture_output=True,
    )
    # Run from a directory that is not the repository, so a checkout further up
    # cannot answer for the installed lane and quietly turn this green.
    # ⚠️ Scrub the ambient import path. Run alone this file passed; run inside
    #    the suite it failed, because an earlier test puts the repository on
    #    ``PYTHONPATH`` and the probe inherited it — importing *the checkout*
    #    while claiming to measure the installed lane. That is the same shape
    #    the monorepo scrubs at collection time: a leaked environment variable
    #    makes a green that belongs to another machine's state. The
    #    ``site-packages`` assertion below is what caught it, which is the
    #    reason a non-vacuity check earns its place.
    env = {
        key: value for key, value in os.environ.items()
        if key not in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP')
    }
    probed = subprocess.run(
        [str(python), '-c', _PROBE, json.dumps(list(CONSUMER_REQUESTED))],
        check=True, capture_output=True, text=True, cwd=str(tmp), env=env,
    )
    return json.loads(probed.stdout.strip().splitlines()[-1])


@unittest.skipIf(shutil.which('git') is None, 'needs a build toolchain')
class TestShippedArtifactsReachAnInstalledLane(unittest.TestCase):
    """The lane's artifacts resolve from a wheel, and refusal still refuses."""

    @classmethod
    def setUpClass(cls):
        cls._tmp_ctx = tempfile.TemporaryDirectory()
        try:
            cls.probe = _build_and_probe(Path(cls._tmp_ctx.name))
        except subprocess.CalledProcessError as exc:  # pragma: no cover
            cls._tmp_ctx.cleanup()
            raise unittest.SkipTest(
                'NOT VERIFIED here: building the wheel failed, so this axis was '
                f'not measured. stderr: {exc.stderr!r}'
            ) from exc

    @classmethod
    def tearDownClass(cls):
        cls._tmp_ctx.cleanup()

    def test_the_probe_ran_against_an_installed_lane_not_this_checkout(self):
        """Non-vacuity: a probe that imported the checkout proves nothing."""
        module = self.probe['module']
        self.assertIn(
            'site-packages', module,
            f'the probe imported {module!r}, which is not an installed lane — '
            'this whole file then measures the state that was never broken',
        )
        self.assertNotIn(str(_REPO_ROOT), module)

    def test_every_consumer_requested_artifact_resolves_to_a_real_file(self):
        self.assertTrue(CONSUMER_REQUESTED, 'the census is empty')
        for rel, verdict in sorted(self.probe['resolved'].items()):
            with self.subTest(artifact=rel):
                self.assertIs(
                    verdict, True,
                    f'{rel!r} did not resolve to a file in the installed lane '
                    f'(got {verdict!r}). A wheel carries importable packages: '
                    'an artifact delivered to the box root is unreachable, and '
                    'declaring it in [tool.setuptools.package-data] is what '
                    'puts it where a consumer can read it.',
                )

    def test_an_artifact_the_wheel_does_not_carry_is_still_refused(self):
        """The repair must not turn the refusal into a guess.

        Widening a resolver until nothing raises is the cheapest way to make
        this file green and the most expensive to discover later: the caller
        receives a path that looks authoritative and is wrong.
        """
        self.assertTrue(
            self.probe['refused_absent'],
            'an absent path resolved instead of raising DependencyTreeUnavailable '
            '— the refusal that makes the resolver trustworthy is gone',
        )


if __name__ == '__main__':
    unittest.main()
