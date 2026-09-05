"""Seals for the conformance feature axis (§6.7 / §6.7.1 / §6.7.2, 2026-09-05).

What this file refuses:

* a contract whose operations are not partitioned by feature, or whose core is
  empty, or whose core has quietly grown;
* a dependency closure that passes everything (vacuous) or refuses a real
  provider (over-strict) — both are checked against measured provider shapes,
  not invented ones;
* the two identifier defects repaired in this wave coming back;
* a publisher that reads an installed copy of what it is publishing.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fcc_test_contracts.headless.api_contract_checker import (  # noqa: E402
    check_api_contract_compatibility,
)
from fcc_test_contracts.headless.api_contract_features import (  # noqa: E402
    CORE_FEATURE_IDS,
    FEATURE_IDS,
    HEADLESS_FEATURES,
    UnknownFeatureError,
    feature_operations,
    validate_feature_membership,
)
from fcc_test_contracts.headless.api_contracts import (  # noqa: E402
    HEADLESS_API_OPERATIONS,
    HEADLESS_API_PATH_PARAMS,
    HEADLESS_API_ROUTES,
    HEADLESS_API_SCHEMAS,
    ApiContractSnapshot,
)
from fcc_test_contracts.headless.contract_identity import (  # noqa: E402
    FeatureScopeError,
    contract_identity_digest,
    feature_scoped_document,
    feature_scoped_identity,
)
from fcc_test_contracts.headless.path_identifier_policy import (  # noqa: E402
    INTEGER_IDENTIFIER_GRANDFATHER,
    PathIdentifierPolicyError,
    validate_path_identifier_policy,
)
from fcc_test_contracts.headless.dependency_closure import (  # noqa: E402
    DEFECT_IDENTIFIERS,
    IDENTIFIER_CLASSES,
    IDENTIFIER_CLASS_DEFECT,
    IDENTIFIER_CLASS_PROVIDER_PRODUCED,
    IdentifierClassError,
    closure_issues,
    identifier_producers,
    validate_identifier_classes,
)

ARTIFACT = PROJECT_ROOT / 'fcc_test_contracts/artifacts/headless_api_contract.v1.json'

#: The core named by §6.7 plus the one §6.7.1 ① added. Spelled out rather than
#: read from the table so that widening core is an edit in TWO places — the
#: judgement warned that the temptation to widen it is the failure mode, and a
#: seal that reads the thing it guards guards nothing.
EXPECTED_CORE_OPERATIONS = frozenset({
    'health_check',
    'headless_api_contract',
    'headless_status',
    'provider_capabilities',
    'provider_ui_descriptor',
})

#: Measured 2026-09-05 from the KC lane's own registry-derived table.
KC_DECLARED = ('test-plan-authoring', 'test-plan-publication', 'measurement-jobs')


class TestTheOperationsArePartitioned(unittest.TestCase):

    def test_every_operation_names_a_declared_feature(self):
        validate_feature_membership(HEADLESS_API_OPERATIONS)
        for name, operation in HEADLESS_API_OPERATIONS.items():
            with self.subTest(name):
                self.assertIn(operation.get('feature'), FEATURE_IDS)

    def test_the_grouping_is_a_partition(self):
        grouped = feature_operations(HEADLESS_API_OPERATIONS)
        flat = [name for names in grouped.values() for name in names]
        self.assertEqual(len(flat), len(set(flat)), 'an operation is in two features')
        self.assertEqual(set(flat), set(HEADLESS_API_OPERATIONS))

    def test_no_feature_is_empty(self):
        grouped = feature_operations(HEADLESS_API_OPERATIONS)
        self.assertEqual(
            [f for f, names in grouped.items() if not names], [],
            'a feature with no operations cannot be served, missed, or judged',
        )

    def test_an_unknown_feature_is_refused_not_absorbed(self):
        polluted = dict(HEADLESS_API_OPERATIONS)
        polluted['health_check'] = dict(polluted['health_check'], feature='invented')
        with self.assertRaises(UnknownFeatureError):
            validate_feature_membership(polluted)


class TestCoreIsSmallAndNonEmpty(unittest.TestCase):
    """§6.7: *"core 를 이보다 넓히려는 유혹을 경계하라"*."""

    def test_core_is_exactly_the_operations_the_judgement_named(self):
        grouped = feature_operations(HEADLESS_API_OPERATIONS)
        served = {name for f in CORE_FEATURE_IDS for name in grouped[f]}
        self.assertEqual(served, EXPECTED_CORE_OPERATIONS)

    def test_core_is_not_empty(self):
        self.assertTrue(CORE_FEATURE_IDS)

    def test_required_features_are_in_scope_without_being_declared(self):
        scoped = feature_scoped_document(ApiContractSnapshot().to_dict(), [])
        self.assertEqual(set(scoped['operations']), EXPECTED_CORE_OPERATIONS)


class TestAbsenceAndZeroAreDifferentValues(unittest.TestCase):
    """§6.7.1 ①: five zeros meant both *"empty queue"* and *"no such queue"*."""

    def test_report_automation_is_optional_on_the_status_snapshot(self):
        schema = HEADLESS_API_SCHEMAS['HeadlessBackendStatusSnapshot']
        self.assertNotIn('report_automation', schema['required'])
        self.assertIn(
            'report_automation', schema['properties'],
            'optional means may be absent, not may not be sent',
        )

    def test_headless_status_is_still_core(self):
        self.assertIn(
            HEADLESS_API_OPERATIONS['headless_status']['feature'],
            CORE_FEATURE_IDS,
        )


class TestTheTwoRepairedIdentifierDefects(unittest.TestCase):

    def test_the_generation_axis_produces_the_name_its_route_consumes(self):
        """Defect 1: route ``{generation_job_id}``, producer field ``job_id``."""
        producers = identifier_producers(
            HEADLESS_API_OPERATIONS, HEADLESS_API_ROUTES, HEADLESS_API_SCHEMAS,
        )
        self.assertEqual(
            producers['generation_job_id'], ('submit_test_plan_generation',),
        )

    def test_no_generation_schema_spells_the_measurement_axis_name(self):
        """Defect 2: ``job_id`` meant two things on two axes."""
        for name in (
            'TestPlanGenerationSubmittedResponse',
            'TestPlanGenerationJobResponse',
            'TestPlanGenerationMetadataResponse',
        ):
            with self.subTest(name):
                properties = HEADLESS_API_SCHEMAS[name]['properties']
                self.assertNotIn('job_id', properties)
                self.assertIn('generation_job_id', properties)

    def test_no_path_parameter_is_spelled_job_id_on_either_axis(self):
        """``job_id`` named two different things and now names neither.

        The generation axis moved to ``generation_job_id`` and the measurement
        axis to ``job_uuid``. The name that was ambiguous is simply gone —
        which is stronger than disambiguating it, because a future author
        cannot reintroduce the ambiguity by reusing a name that still exists.
        """
        self.assertNotIn('job_id', HEADLESS_API_PATH_PARAMS)
        for name, (_method, path) in HEADLESS_API_ROUTES.items():
            with self.subTest(name):
                self.assertNotIn('{job_id}', path)

    def test_every_axis_identifier_has_exactly_one_minimal_producer(self):
        producers = identifier_producers(
            HEADLESS_API_OPERATIONS, HEADLESS_API_ROUTES, HEADLESS_API_SCHEMAS,
        )
        self.assertEqual(producers['generation_job_id'],
                         ('submit_test_plan_generation',))
        self.assertEqual(producers['job_uuid'], ('submit_measurement_job',))


class TestTheIdentifierClasses(unittest.TestCase):

    def test_the_classes_and_the_surface_agree(self):
        validate_identifier_classes(
            HEADLESS_API_OPERATIONS, HEADLESS_API_ROUTES, HEADLESS_API_SCHEMAS,
        )

    def test_every_path_parameter_is_classed(self):
        self.assertEqual(set(IDENTIFIER_CLASSES), set(HEADLESS_API_PATH_PARAMS))

    def test_the_defect_ratchet_is_empty_and_stays_empty(self):
        declared = {
            identifier
            for identifier, klass in IDENTIFIER_CLASSES.items()
            if klass == IDENTIFIER_CLASS_DEFECT
        }
        self.assertEqual(declared, set(DEFECT_IDENTIFIERS))
        self.assertEqual(
            set(DEFECT_IDENTIFIERS), set(),
            'a naming mismatch may not be absorbed by classing it a defect — '
            'the one member this ratchet ever held was repaired the same day',
        )

    def test_a_new_unproducible_identifier_cannot_be_classed_as_produced(self):
        """The class declaration must not become where defects are legitimised."""
        stripped = dict(HEADLESS_API_OPERATIONS)
        stripped.pop('submit_test_plan_generation')
        with self.assertRaises(IdentifierClassError):
            validate_identifier_classes(
                stripped, HEADLESS_API_ROUTES, HEADLESS_API_SCHEMAS,
            )

    def test_project_id_and_session_id_are_exempt_not_produced(self):
        """Without the exemptions every provider is red for the same reason."""
        for identifier in ('project_id', 'session_id'):
            with self.subTest(identifier):
                self.assertNotEqual(
                    IDENTIFIER_CLASSES[identifier],
                    IDENTIFIER_CLASS_PROVIDER_PRODUCED,
                )


class TestTheClosureDerivation(unittest.TestCase):
    """Each narrowing in the production rule, checked by what it excludes."""

    def setUp(self):
        self.producers = identifier_producers(
            HEADLESS_API_OPERATIONS, HEADLESS_API_ROUTES, HEADLESS_API_SCHEMAS,
        )

    def test_it_reproduces_the_judgements_worked_example(self):
        self.assertEqual(
            self.producers['draft_id'],
            ('create_test_plan_draft', 'import_test_plan'),
        )

    def test_handing_back_what_it_was_given_is_not_producing(self):
        self.assertNotIn('get_test_plan_draft', self.producers['draft_id'])

    def test_mentioning_someone_elses_identity_is_not_producing(self):
        self.assertNotIn('get_published_test_plan', self.producers['project_id'])
        self.assertNotIn('get_published_test_plan', self.producers['draft_id'])

    def test_discovery_is_not_creation(self):
        self.assertNotIn('list_test_plan_drafts', self.producers['draft_id'])


class TestTheClosureIsNeitherVacuousNorOverStrict(unittest.TestCase):

    def _served(self, features):
        grouped = feature_operations(HEADLESS_API_OPERATIONS)
        scope = set(features) | set(CORE_FEATURE_IDS)
        return {name for f in scope for name in grouped[f]}

    def _issues(self, served):
        return closure_issues(
            served, HEADLESS_API_OPERATIONS, HEADLESS_API_ROUTES,
            HEADLESS_API_SCHEMAS,
        )

    def test_the_reference_provider_shape_is_not_red(self):
        """Measured 2026-09-05: FCC registers all 40 operations."""
        self.assertEqual(self._issues(set(HEADLESS_API_OPERATIONS)), [])

    def test_the_kc_shape_is_not_red(self):
        served = self._served(KC_DECLARED)
        self.assertEqual(len(served), 21)
        self.assertEqual(self._issues(served), [])

    def test_an_alternative_producer_satisfies_the_closure(self):
        """Serve import but not create and you can still make a draft."""
        served = self._served(KC_DECLARED) - {'create_test_plan_draft'}
        self.assertEqual(self._issues(served), [])

    def test_a_door_with_no_key_is_red(self):
        served = self._served(KC_DECLARED) - {
            'create_test_plan_draft', 'import_test_plan',
        }
        identifiers = {issue['identifier'] for issue in self._issues(served)}
        self.assertEqual(identifiers, {'draft_id'})

    def test_reading_a_generation_job_you_cannot_submit_is_red(self):
        """This edge exists only because defect 1 was repaired in this wave."""
        served = self._served([]) | {'get_test_plan_generation'}
        self.assertEqual(
            [issue['identifier'] for issue in self._issues(served)],
            ['generation_job_id'],
        )


class TestTheDeclaredFeaturesMode(unittest.TestCase):

    def setUp(self):
        self.ssot = ApiContractSnapshot().to_dict()
        self.kc = dict(feature_scoped_document(self.ssot, KC_DECLARED))
        self.kc['provider'] = {
            'provider_id': 'kc-unlicensed-headless',
            'product_line': 'unlicensed-conducted',
            'contract_family': 'fcc-conducted-headless',
        }

    def test_full_mode_refuses_a_partial_provider(self):
        """The state this wave exists to end."""
        result = check_api_contract_compatibility(self.kc, self.ssot)
        self.assertFalse(result.compatible)

    def test_declared_features_mode_admits_it(self):
        result = check_api_contract_compatibility(
            self.kc, self.ssot,
            mode='declared-features', declared_features=KC_DECLARED,
        )
        self.assertTrue(result.compatible, [i.to_dict() for i in result.issues])

    def test_declaring_what_you_do_not_serve_is_refused(self):
        result = check_api_contract_compatibility(
            self.kc, self.ssot,
            mode='declared-features',
            declared_features=list(KC_DECLARED) + ['report-automation'],
        )
        self.assertFalse(result.compatible)

    def test_an_undeclarable_feature_is_named_rather_than_ignored(self):
        result = check_api_contract_compatibility(
            self.kc, self.ssot,
            mode='declared-features', declared_features=['invented'],
        )
        self.assertFalse(result.compatible)
        self.assertEqual(
            [issue.code for issue in result.issues], ['unknown_declared_feature'],
        )

    def test_the_mode_and_its_argument_cannot_be_separated(self):
        with self.assertRaises(ValueError):
            check_api_contract_compatibility(self.kc, self.ssot,
                                             mode='declared-features')
        with self.assertRaises(ValueError):
            check_api_contract_compatibility(self.kc, self.ssot,
                                             declared_features=KC_DECLARED)

    def test_the_closure_arm_is_wired_into_the_mode(self):
        crippled = dict(self.kc)
        crippled['operations'] = {
            name: operation
            for name, operation in self.kc['operations'].items()
            if name not in {'create_test_plan_draft', 'import_test_plan'}
        }
        result = check_api_contract_compatibility(
            crippled, self.ssot,
            mode='declared-features', declared_features=KC_DECLARED,
        )
        self.assertIn(
            'dependency_closure_violation',
            {issue.code for issue in result.issues},
        )


class TestTheFeatureScopeIsAConservativeExtension(unittest.TestCase):

    def setUp(self):
        self.ssot = ApiContractSnapshot().to_dict()

    def test_declaring_everything_reproduces_the_whole_contract_digest(self):
        every = [f for f, p in HEADLESS_FEATURES.items() if not p['required']]
        self.assertEqual(
            feature_scoped_identity(self.ssot, every)['digest'],
            contract_identity_digest(self.ssot),
        )

    def test_a_narrower_scope_is_a_different_digest(self):
        self.assertNotEqual(
            feature_scoped_identity(self.ssot, KC_DECLARED)['digest'],
            contract_identity_digest(self.ssot),
        )

    def test_the_scope_carries_only_schemas_it_can_reach(self):
        scoped = feature_scoped_document(self.ssot, [])
        self.assertLess(len(scoped['schemas']), len(self.ssot['schemas']))
        for operation in scoped['operations'].values():
            for name in (operation.get('request'), operation.get('response')):
                if name:
                    self.assertIn(name, scoped['schemas'])

    def test_an_undeclarable_feature_raises_rather_than_scoping_to_nothing(self):
        with self.assertRaises(FeatureScopeError):
            feature_scoped_document(self.ssot, ['invented'])


class TestThePublishedArtifactIsThisTree(unittest.TestCase):
    """§6.7.3: *"두 유도가 같은 출처를 쓰면 대조는 항등식이다."*"""

    def test_the_artifact_matches_the_source(self):
        shipped = json.loads(ARTIFACT.read_text(encoding='utf-8'))
        self.assertEqual(
            contract_identity_digest(shipped),
            contract_identity_digest(ApiContractSnapshot().to_dict()),
            'regenerate: python3 scripts/export_headless_api_contract.py',
        )

    def test_the_artifact_carries_the_feature_table(self):
        shipped = json.loads(ARTIFACT.read_text(encoding='utf-8'))
        self.assertEqual(set(shipped.get('features') or {}), set(FEATURE_IDS))

    def test_the_publisher_reads_this_repository_not_an_installed_copy(self):
        """The seal that would have caught the 2026-09-05 publisher defect.

        Run as a subprocess with a bare environment, exactly as an operator
        would. While the script omitted ``PROJECT_ROOT`` from ``sys.path`` it
        published the interpreter's *installed* ``fcc_test_contracts`` — which
        still carried a defect this repository had already repaired — and the
        bytes differed here.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'contract.json'
            completed = subprocess.run(
                [sys.executable,
                 str(PROJECT_ROOT / 'scripts/export_headless_api_contract.py'),
                 str(output)],
                cwd=tmp, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(output.read_text(encoding='utf-8')),
                json.loads(ARTIFACT.read_text(encoding='utf-8')),
                'the publisher and the shipped artifact disagree — the '
                'publisher is reading a different fcc_test_contracts than '
                'this tree',
            )


if __name__ == '__main__':  # pragma: no cover
    unittest.main()


class TestPathIdentifiersAreOpaque(unittest.TestCase):
    """OWASP API1:2023 + Zalando rule 174, enforced rather than recommended.

    The measurement route used to take the storage primary key. That is
    enumerable (OWASP's stated reason), it publishes the laboratory's job count
    because the column is AUTOINCREMENT (Zalando rule 144's stated reason), and
    a per-provider integer collides across providers (this contract's own
    reason). All three are closed by one change and this class refuses its
    return.
    """

    def test_the_policy_holds_for_the_shipped_contract(self):
        validate_path_identifier_policy(HEADLESS_API_PATH_PARAMS)

    def test_a_new_integer_path_identifier_is_refused(self):
        with self.assertRaises(PathIdentifierPolicyError):
            validate_path_identifier_policy(
                dict(HEADLESS_API_PATH_PARAMS,
                     invented_id={'type': 'integer', 'minimum': 1}),
            )

    def test_the_ratchet_must_shrink_when_a_surface_migrates(self):
        """A grandfathered id that became opaque may not stay on the list."""
        migrated = dict(HEADLESS_API_PATH_PARAMS)
        migrated['session_id'] = {'type': 'string', 'minLength': 1}
        with self.assertRaises(PathIdentifierPolicyError):
            validate_path_identifier_policy(migrated)

    def test_every_grandfathered_entry_carries_its_reason(self):
        for name, reason in INTEGER_IDENTIFIER_GRANDFATHER.items():
            with self.subTest(name):
                self.assertGreater(
                    len(reason), 40,
                    'a ratchet entry without an argument is an exemption',
                )

    def test_the_measurement_job_no_longer_publishes_its_primary_key(self):
        for name in ('MeasurementJobSubmitted', 'MeasurementJobSnapshot'):
            with self.subTest(name):
                schema = HEADLESS_API_SCHEMAS[name]
                self.assertNotIn('id', schema['properties'])
                self.assertIn('job_uuid', schema['required'])

    def test_the_stop_response_echoes_the_identifier_that_addressed_it(self):
        schema = HEADLESS_API_SCHEMAS['StopMeasurementJobResponse']
        self.assertIn('job_uuid', schema['required'])
        self.assertNotIn('job_id', schema['properties'])
        _method, path = HEADLESS_API_ROUTES['stop_measurement_job']
        self.assertIn('{job_uuid}', path)
