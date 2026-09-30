# Adapted synthetic fixtures and selected cache tests, MIT; newly authored product tests Apache-2.0.
from __future__ import annotations
import base64
import contextlib, copy, io, json, sqlite3, tempfile, unittest, hashlib, ast
from pathlib import Path
from unittest.mock import patch
from trio_triage import contracts as contract
from trio_triage.search.cache_source import TriageCache
from trio_triage.search.cache_index import CacheIndex, encode_response
from trio_triage.search.projections import ProjectionPolicy, pointer_get, project, reproduce
from trio_triage.search.models import canonical, sha256
START = '2026-09-27T12:00:00Z'
FETCHED = '2026-09-27T12:01:00Z'
END = '2026-09-27T12:02:00Z'
REPOSITORY = contract.repository('example/triage', database_id=42, node_id='R_synthetic')

def sealed(value):
    return {**value, 'checksum': sha256(canonical(value))}

def write_object(root, value, format='json'):
    text = canonical(value) + '\n' if format == 'json' else value
    ref = contract.artifact_ref(text, format)
    (root / 'objects' / contract.object_name(ref)).write_text(text, encoding='utf-8')
    return ref

def publish(root, records, requested=None):
    manifest = contract.seal_snapshot({'schema_version': 1, 'artifact': 'evidence-snapshot', 'repository': REPOSITORY, 'started_at': START, 'completed_at': END, 'requested_components': sorted(requested or records[0]['components']), 'items': records})
    (root / 'snapshots' / (manifest['snapshot_id'] + '.json')).write_text(canonical(manifest) + '\n', encoding='utf-8')
    return manifest

def make_cache(root: Path, count=4, repeat=1):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'objects').mkdir(exist_ok=True)
    (root / 'snapshots').mkdir(exist_ok=True)
    (root / 'corpora').mkdir(exist_ok=True)
    (root / 'cache.json').write_text(canonical({'schema_version': 1, 'artifact': 'evidence-cache', 'repository': REPOSITORY}) + '\n', encoding='utf-8')
    records = []
    for n in range(1, count + 1):
        kind = 'pr' if n % 2 == 0 else 'issue'
        identity = {'kind': kind, 'number': n, 'database_id': 1000 + n, 'node_id': f'{kind}_synthetic_{n}'}
        revision = {'updated_at': START, 'base_sha': 'a' * 40 if kind == 'pr' else None, 'head_sha': 'b' * 40 if kind == 'pr' else None}
        uri = f"https://github.com/example/triage/{('pull' if kind == 'pr' else 'issues')}/{n}"
        summary = {'number': n, 'kind': kind, 'state': 'open', 'source_state': 'open', 'title': f'Terminal suspend example {n}', 'body': 'A terminal fails after suspend. Different causes need review.', 'html_url': uri, 'user': {'login': 'demo'}, 'labels': [{'name': 'terminal'}, {'name': 'synthetic'}], 'inventory': {'artifact': 'inventory-observation', 'schema_version': 1, 'repository': REPOSITORY, 'started_at': START, 'completed_at': END, 'endpoint': 'repos/example/triage/issues?state=open&per_page=100', 'pages': 1, 'pagination_complete': True, 'mode': 'full', 'since': None, 'raw_sha256': '0' * 64}}
        patch = '@@ -1 +1 @@\n-old\n+resume terminal café 🙂\n'
        diff = 'diff --git a/src/terminal.py b/src/terminal.py\n--- a/src/terminal.py\n+++ b/src/terminal.py\n' + patch
        payloads = {'summary': summary, 'comments': [{'id': n * 100 + i, 'body': 'Resume terminal after suspend café 🙂. ' * repeat + f'comment {i}', 'html_url': uri + f'#issuecomment-{n * 100 + i}'} for i in range(2)], 'files': [{'filename': 'src/terminal.py', 'status': 'modified', 'patch': patch}], 'diff': diff, 'reviews': [{'id': n * 1000, 'body': 'Alternative terminal fix needs review.', 'state': 'COMMENTED'}], 'review_comments': [{'id': n * 1000 + 1, 'body': 'This resume path may affect another cause.', 'path': 'src/terminal.py', 'diff_hunk': patch}], 'checks': [{'kind': 'check_run', 'repository': REPOSITORY, 'head_sha': 'b' * 40, 'fetched_at': FETCHED, 'resource': '/synthetic/check-runs', 'data': {'id': n, 'name': 'terminal-tests', 'status': 'completed', 'conclusion': 'success', 'output': {'title': 'Resume checks', 'summary': 'Synthetic tests pass', 'text': 'No live validation implied'}}}], 'closing_issues': [{'repository': REPOSITORY, 'identity': {'kind': 'issue', 'number': 1, 'database_id': None, 'node_id': 'issue_synthetic_1'}, 'url': 'https://github.com/example/triage/issues/1', 'state': 'open', 'updated_at': START}], 'timeline': [{'id': n, 'event': 'commented', 'body': 'A suspend observation, not approval.'}]}
        components = {}
        for name, value in payloads.items():
            if kind == 'issue' and name in contract.PR_ONLY:
                components[name] = {'status': 'not_applicable', 'fetched_at': None, 'source': None, 'revision': revision, 'expected_count': None, 'received_count': None, 'pagination_complete': None, 'truncated': False, 'error': None, 'object': None}
                continue
            ref = write_object(root, value, 'diff' if name == 'diff' else 'json')
            collection = name in contract.COLLECTIONS
            components[name] = {'status': 'complete', 'fetched_at': FETCHED, 'source': {'transport': 'rest', 'resource': f'/repos/example/triage/issues/{n}/{name}'}, 'revision': revision, 'expected_count': len(value) if collection else None, 'received_count': len(value) if collection else None, 'pagination_complete': True if collection else None, 'truncated': False, 'error': None, 'object': ref}
        records.append({'identity': identity, 'revision': revision, 'components': components})
    manifest = publish(root, records)
    plan = sealed({'artifact': 'evidence-corpus-plan', 'schema_version': 1, 'repository': REPOSITORY, 'inventory_snapshot': manifest['snapshot_id'], 'scope': 'open-items', 'profile': 'backlog', 'max_age': 86400, 'members': sorted((r['identity'] for r in records), key=lambda r: (r['kind'], r['number']))})
    corpus = plan['checksum']
    (root / 'corpora' / (corpus + '.plan.json')).write_text(canonical(plan) + '\n', encoding='utf-8')
    state = sealed({'artifact': 'evidence-corpus-state', 'schema_version': 1, 'plan_id': corpus, 'updated_at': END, 'status': 'finished', 'items': {f"{r['identity']['kind']}:{r['identity']['number']}": {'attempts': 1, 'snapshot_id': manifest['snapshot_id'], 'outcome': 'complete', 'error': None} for r in records}, 'last_run': None})
    (root / 'corpora' / (corpus + '.state.json')).write_text(canonical(state) + '\n', encoding='utf-8')
    return (manifest, corpus)

def evidence_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for directory in ('objects', 'snapshots', 'corpora') for p in (root / directory).glob('*')} | {'cache.json': (root / 'cache.json').read_bytes()}

class CacheTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'cache'
        self.manifest, self.corpus = make_cache(self.root)
        self.snapshot = self.manifest['snapshot_id']
        self.source = TriageCache(self.root)
        self.database = self.root.parent / 'reposition/search.sqlite'
        self.build()

    def build(self, **kwargs):
        return CacheIndex.build(self.source, self.database, snapshot=self.snapshot, **kwargs)

    def query(self, text='terminal', **kwargs):
        with CacheIndex(self.database) as index:
            return index.query(self.source, text, snapshot=self.snapshot, **kwargs)

    def state(self):
        return json.loads((self.root / 'corpora' / (self.corpus + '.state.json')).read_text())

    def change_state(self, state):
        state.pop('checksum', None)
        (self.root / 'corpora' / (self.corpus + '.state.json')).write_text(canonical(sealed(state)) + '\n')

    def test_queries_verify_returned_sources_and_complete_wire_budget(self):
        result = self.query('SUSPEND café 🙂', max_bytes=7000, fragment_bytes=80)
        encoded = encode_response(result).encode('utf-8')
        self.assertEqual(result['budget']['used_bytes'], len(encoded))
        self.assertLessEqual(len(encoded), 7000)
        self.assertEqual(result['requests'], 0)
        self.assertTrue(result['items'])
        self.assertIsNotNone(result['continuation'])
        for item in result['items']:
            for fragment in item['fragments']:
                self.assertTrue(fragment['verified'])
                excerpt = fragment['excerpt']
                self.assertLessEqual(len(excerpt['text'].encode('utf-8')), 80)
                self.assertEqual(excerpt['sha256'], sha256(excerpt['text']))
                record = next((r for r in self.manifest['items'] if r['identity'] == item['identity']))
                payload = self.source.object(fragment['component'], record['components'][fragment['component']], item['identity']['kind'])
                original = payload if fragment['locator']['pointer'] is None else pointer_get(json.loads(payload), fragment['locator']['pointer'])
                self.assertEqual(original.encode('utf-8')[excerpt['start']:excerpt['end']].decode('utf-8'), excerpt['text'])

    def test_components_fields_and_item_filters_apply_before_candidate_cap(self):
        result = self.query('terminal', components=('files', 'review_comments'), fields=('path',), kind='pr', state='open', label='terminal', author='demo', after='2026-09-27T12:00:00Z', before='2026-09-27T12:02:00Z', max_snippets_per_item=1)
        self.assertEqual({i['identity']['number'] for i in result['items']}, {2, 4})
        self.assertFalse(self.query(label='absent')['items'])
        self.assertFalse(self.query(after='2027-01-01T00:00:00Z')['items'])
        self.assertFalse(self.query(author='someone-else')['items'])
        self.assertFalse(result['diagnostics']['score_is_probability'])
        self.assertTrue(all((f['locator']['field'] == 'path' for i in result['items'] for f in i['fragments'])))

    def test_all_nine_components_are_searchable(self):
        for component, query in {'summary': 'suspend', 'comments': 'café', 'files': 'terminal', 'diff': 'café', 'reviews': 'Alternative', 'review_comments': 'another cause', 'checks': 'Synthetic', 'closing_issues': 'issues', 'timeline': 'observation'}.items():
            with self.subTest(component=component):
                result = self.query(query, components=(component,), max_snippets_per_item=1)
                self.assertTrue(result['items'])
                self.assertTrue(all((f['component'] == component for i in result['items'] for f in i['fragments'])))

    def test_exact_phrases_and_title_path_weights(self):
        result = self.query('"fails after suspend"', components=('summary',), fields=('body',))
        self.assertEqual(result['diagnostics']['ranked_groups'], 4)
        self.assertIn('fails after suspend', result['items'][0]['fragments'][0]['excerpt']['text'])
        self.assertFalse(self.query('"after fails suspend"')['items'])
        self.assertEqual(self.query('terminal', components=('summary',))['items'][0]['fragments'][0]['locator']['field'], 'title')

    def test_item_diversity_and_fragment_mode(self):
        result = self.query(max_snippets_per_item=1)
        self.assertTrue(all((len(i['fragments']) == 1 for i in result['items'])))
        self.assertGreater(result['diagnostics']['fragments_omitted_per_item'], 0)
        fragments = self.query(fragment_mode=True, max_bytes=60000)
        self.assertGreater(len(fragments['items']), len(result['items']))
        self.assertTrue(all((len(i['fragments']) == 1 for i in fragments['items'])))

    def test_pagination_pages_matches_and_binds_all_query_limits(self):
        first = self.query(limit=1, max_snippets_per_item=1)
        seen = {first['items'][0]['identity']['number']}
        cursor = first['continuation']
        while cursor:
            page = self.query(limit=1, max_snippets_per_item=1, cursor=cursor)
            self.assertEqual(len(page['items']), 1)
            n = page['items'][0]['identity']['number']
            self.assertNotIn(n, seen)
            seen.add(n)
            cursor = page['continuation']
        self.assertEqual(seen, {1, 2, 3, 4})
        for change in ({'limit': 2}, {'max_bytes': 13000}, {'fragment_bytes': 80}, {'components': ('comments',)}, {'fields': ('body',)}, {'label': 'terminal'}, {'fragment_mode': True}, {'max_age': 0}, {'candidates': 100}, {'max_verify_bytes': 4096}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'continuation'):
                options = {'limit': 1, 'max_snippets_per_item': 1, 'cursor': first['continuation'], **change}
                self.query(**options)
        with self.assertRaisesRegex(ValueError, 'continuation'):
            self.query('different query', limit=1, max_snippets_per_item=1, cursor=first['continuation'])

    def test_candidate_and_budget_omissions_are_explicit(self):
        result = self.query(candidates=1, max_snippets_per_item=1)
        self.assertTrue(result['diagnostics']['candidates_truncated'])
        self.assertEqual(result['diagnostics']['candidates_considered'], 1)
        with self.assertRaisesRegex(ValueError, 'byte budget'):
            self.query(max_bytes=512)
        with self.assertRaisesRegex(ValueError, 'verification byte ceiling'):
            self.query(max_verify_bytes=1)

    def test_only_returned_source_objects_are_read_and_shared_objects_read_once(self):
        original = self.source.object
        with patch.object(self.source, 'object', wraps=original) as reader:
            result = self.query('terminal', components=('files',), fields=('path',))
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(reader.call_count, 1)

    def test_corrupt_object_fails_closed_without_echoing_source_text(self):
        reference = self.query('café', components=('comments',))['items'][0]['fragments'][0]['object']
        path = self.source.path('objects', reference['sha256'] + '.json')
        path.write_bytes(b'PRIVATE SOURCE DO NOT ECHO')
        with self.assertRaisesRegex(ValueError, 'failed verification') as error:
            self.query('café', components=('comments',))
        self.assertNotIn('PRIVATE SOURCE', str(error.exception))

    def test_bad_manifest_and_future_source_version_fail(self):
        path = self.root / 'snapshots' / (self.snapshot + '.json')
        value = json.loads(path.read_text())
        value['items'][0]['revision']['updated_at'] = '2026-09-28T00:00:00Z'
        path.write_text(canonical(value))
        with self.assertRaisesRegex(ValueError, 'source selection changed'):
            self.query()
        metadata = json.loads((self.root / 'cache.json').read_text())
        metadata['schema_version'] = 2
        (self.root / 'cache.json').write_text(canonical(metadata))
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            TriageCache(self.root)

    def test_index_corruption_and_explicit_recovery(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE manifest SET data='broken'")
        with self.assertRaises(ValueError):
            self.query()
        with self.assertRaises(ValueError):
            self.build(replace=True)
        self.build(recover=True)
        self.assertTrue(self.query()['items'])

    def test_corrupt_projection_never_searches_nearby_source(self):
        identifier = self.query()['items'][0]['fragments'][0]['unit_id']
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE units SET projection=X'00' WHERE id=?", (identifier,))
        with self.assertRaisesRegex(ValueError, 'corrupt; rebuild'):
            self.query()

    def test_dropped_fts_table_has_explicit_rebuild_path(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute('DROP TABLE evidence')
        with self.assertRaisesRegex(ValueError, 'rebuild'):
            self.query()

    def test_false_fts_postings_cannot_quote_an_unrelated_source(self):
        with sqlite3.connect(self.database) as connection:
            rowid = connection.execute('SELECT min(rowid) FROM units').fetchone()[0]
            connection.execute('INSERT INTO evidence(rowid,text) VALUES(?,?)', (rowid, 'inventedmarker'))
        with self.assertRaisesRegex(ValueError, 'postings.*rebuild'):
            self.query('inventedmarker')

    def test_future_index_version_is_not_downgraded_even_by_recovery(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute('PRAGMA user_version=2')
        before = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, 'upgrade'):
            self.build(recover=True)
        self.assertEqual(before, self.database.read_bytes())

    def test_foreign_repository_and_stable_id_conflicts_fail_closed(self):
        metadata_path = self.root / 'cache.json'
        metadata = json.loads(metadata_path.read_text())
        metadata['repository']['database_id'] = 999
        metadata_path.write_text(canonical(metadata))
        foreign = TriageCache(self.root)
        with CacheIndex(self.database) as index, self.assertRaises(ValueError):
            index.query(foreign, 'terminal', snapshot=self.snapshot)
        with CacheIndex(self.database) as index, self.assertRaises(ValueError):
            index.info(foreign)
        with self.assertRaises(ValueError):
            CacheIndex.build(foreign, self.database, snapshot=self.snapshot, replace=True)

    def test_metadata_inspection_checks_identity_and_scope_without_a_source_audit(self):
        before=evidence_bytes(self.root)
        with CacheIndex(self.database) as index:
            info=index.info(self.source,snapshot=self.snapshot)
            self.assertEqual(info["repository"],self.manifest["repository"])
            self.assertFalse(info["source_checkpoint_verified"])
            self.assertFalse(info["source_payloads_verified"])
            with self.assertRaises(ValueError):index.info(self.source,corpus=self.corpus)
        self.assertEqual(before,evidence_bytes(self.root))

    def test_failed_build_keeps_previous_index_and_cleans_temporaries(self):
        before = self.database.read_bytes()
        for limits in ({'max_units': 1}, {'max_index_bytes': 65536}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.build(replace=True, **limits)
            self.assertEqual(before, self.database.read_bytes())
            self.assertEqual(list(self.database.parent.glob('*.building')), [])
            self.assertFalse(self.database.with_name('search.sqlite.build-lock').exists())
        self.assertTrue(self.query()['items'])

    def test_source_changes_during_build_never_publish(self):
        before = self.database.read_bytes()
        with patch.object(self.source, 'checkpoint', side_effect=[self.source.checkpoint(snapshot=self.snapshot), 'changed']), self.assertRaisesRegex(ValueError, 'changed during build'):
            self.build(replace=True)
        self.assertEqual(before, self.database.read_bytes())

    def test_index_build_and_reads_do_not_mutate_evidence_or_corpus_progress(self):
        before = evidence_bytes(self.root)
        self.build(replace=True)
        result = self.query()
        unit = result['items'][0]['fragments'][0]['unit_id']
        with CacheIndex(self.database) as index:
            index.retrieve(self.source, (unit,), checkpoint=result['checkpoint'], snapshot=self.snapshot)
        self.assertEqual(before, evidence_bytes(self.root))
        with self.assertRaisesRegex(ValueError, 'read-only'):
            CacheIndex.build(self.source, self.root / 'objects/forbidden.sqlite', snapshot=self.snapshot)

    def test_corpus_membership_and_progress_are_exact(self):
        CacheIndex.build(self.source, self.database, corpus=self.corpus, replace=True)
        with CacheIndex(self.database) as index:
            first = index.query(self.source, 'terminal', corpus=self.corpus, limit=1)
            self.assertEqual(first['coverage']['selected_members'], 4)
            state = self.state()
            state['updated_at'] = '2026-09-27T12:03:00Z'
            self.change_state(state)
            with self.assertRaisesRegex(ValueError, 'source selection changed'):
                index.query(self.source, 'terminal', corpus=self.corpus, limit=1, cursor=first['continuation'])
            with self.assertRaisesRegex(ValueError, 'scope differs'):
                index.query(self.source, 'terminal', snapshot=self.snapshot)

    def test_unstarted_corpus_keeps_missing_members_visible(self):
        (self.root / 'corpora' / (self.corpus + '.state.json')).unlink()
        CacheIndex.build(self.source, self.database, corpus=self.corpus, replace=True)
        with CacheIndex(self.database) as index:
            result = index.query(self.source, 'terminal', corpus=self.corpus)
        self.assertFalse(result['items'])
        self.assertEqual(result['coverage']['missing_members'], 4)
        self.assertEqual(result['coverage']['outcomes']['pending'], 4)

    def test_new_partial_corpus_observation_is_not_hidden_by_old_complete_one(self):
        CacheIndex.build(self.source, self.database, corpus=self.corpus, replace=True)
        records = copy.deepcopy(self.manifest['items'])
        comment = records[1]['components']['comments']
        comment.update(status='partial', error='Synthetic unfinished page', truncated=True)
        newer = publish(self.root, records)
        state = self.state()
        state['items']['pr:2'].update(snapshot_id=newer['snapshot_id'], outcome='gaps')
        self.change_state(state)
        with CacheIndex(self.database) as index, self.assertRaisesRegex(ValueError, 'source selection changed'):
            index.query(self.source, 'terminal', corpus=self.corpus)
        CacheIndex.build(self.source, self.database, corpus=self.corpus, replace=True)
        with CacheIndex(self.database) as index:
            result = index.query(self.source, 'café', corpus=self.corpus, components=('comments',), kind='pr', max_snippets_per_item=1)
        item = next((i for i in result['items'] if i['identity']['number'] == 2))
        self.assertEqual(item['fragments'][0]['snapshot_id'], newer['snapshot_id'])
        self.assertIn('partial', item['fragments'][0]['problems'])

    def test_rebuilt_index_invalidates_old_query_and_retrieval_checkpoints(self):
        first = self.query(limit=1)
        self.build(replace=True)
        with self.assertRaisesRegex(ValueError, 'continuation'):
            self.query(limit=1, cursor=first['continuation'])
        unit = first['items'][0]['fragments'][0]['unit_id']
        with CacheIndex(self.database) as index, self.assertRaisesRegex(ValueError, 'checkpoint changed'):
            index.retrieve(self.source, (unit,), checkpoint=first['checkpoint'], snapshot=self.snapshot)

    def test_object_limits_and_symlinks_fail_before_reading_unbounded_content(self):
        tiny = TriageCache(self.root, max_object_bytes=16)
        with self.assertRaisesRegex(ValueError, 'failed verification'):
            CacheIndex.build(tiny, self.database, snapshot=self.snapshot, replace=True)
        reference = self.query('café', components=('comments',))['items'][0]['fragments'][0]['object']
        object_path = self.source.path('objects', reference['sha256'] + '.json')
        real = object_path.with_suffix('.saved')
        object_path.rename(real)
        object_path.symlink_to(real)
        with self.assertRaisesRegex(ValueError, 'verification'):
            self.query('café', components=('comments',))

    def test_numeric_anchor_selects_exact_summary_without_relaxing_filters(self):
        result = self.query('#3 unrelated missing terms', max_snippets_per_item=1)
        self.assertEqual(result['items'][0]['identity']['number'], 3)
        self.assertEqual(result['items'][0]['fragments'][0]['reason'], 'explicit-anchor')
        self.assertFalse(self.query('#3 nonexistent', kind='pr')['items'])
        self.assertFalse(self.query('#3 nonexistent', components=('comments',))['items'])

    def test_open_index_handle_rejects_atomic_replacement(self):
        with CacheIndex(self.database) as index:
            first = index.query(self.source, 'terminal', snapshot=self.snapshot, limit=1)
            self.build(replace=True)
            with self.assertRaisesRegex(ValueError, 'was replaced'):
                index.query(self.source, 'terminal', snapshot=self.snapshot, limit=1, cursor=first['continuation'])

    def test_read_transaction_binds_index_rows_through_resolution(self):
        with CacheIndex(self.database) as index:
            original = index._verify

            def verify(*args, **kwargs):
                self.assertTrue(index.connection.in_transaction)
                return original(*args, **kwargs)
            with patch.object(index, '_verify', side_effect=verify):
                index.query(self.source, 'terminal', snapshot=self.snapshot)
            self.assertFalse(index.connection.in_transaction)

    def test_fixed_snapshot_ignores_unrelated_newer_partial_history(self):
        records = copy.deepcopy(self.manifest['items'])
        records[0]['components']['comments'].update(status='partial', truncated=True, error='New synthetic partial observation')
        newer = publish(self.root, records)
        self.assertNotEqual(newer['snapshot_id'], self.snapshot)
        result = self.query('café', components=('comments',), max_snippets_per_item=1)
        self.assertTrue(all((f['snapshot_id'] == self.snapshot for i in result['items'] for f in i['fragments'])))

    def test_source_progress_change_during_verification_prevents_response(self):
        CacheIndex.build(self.source, self.database, corpus=self.corpus, replace=True)
        original = self.source.object

        def changed(*args, **kwargs):
            payload = original(*args, **kwargs)
            state = self.state()
            state['updated_at'] = '2026-09-27T12:03:00Z'
            self.change_state(state)
            return payload
        with patch.object(self.source, 'object', side_effect=changed), CacheIndex(self.database) as index, self.assertRaisesRegex(ValueError, 'source selection changed'):
            index.query(self.source, 'terminal', corpus=self.corpus)

    def test_corpus_cannot_claim_complete_when_selected_component_is_partial(self):
        records = copy.deepcopy(self.manifest['items'])
        records[1]['components']['comments'].update(status='partial', truncated=True, error='Synthetic missing page')
        partial = publish(self.root, records)
        state = self.state()
        state['items']['pr:2']['snapshot_id'] = partial['snapshot_id']
        self.change_state(state)
        with self.assertRaisesRegex(ValueError, 'incomplete evidence'):
            CacheIndex.build(self.source, self.database, corpus=self.corpus, replace=True)

    def test_validation_rejects_bad_limits_filters_and_cursors(self):
        for options in ({'limit': 0}, {'fragment_bytes': True}, {'max_age': -1}, {'max_verify_bytes': 0}, {'components': ('unknown',)}, {'kind': 'other'}, {'state': 'unknown-state'}, {'label': ''}, {'after': 'invalid'}, {'after': '2027-01-01T00:00:00Z', 'before': END}, {'min_score': float('nan')}, {'cursor': '%%%'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.query(**options)

class ProjectionTests(unittest.TestCase):

    def test_deterministic_unicode_chunks_reproduce_original_values(self):
        policy = ProjectionPolicy(max_bytes=256, overlap_bytes=32, max_lines=3)
        payload = canonical([{'id': 1, 'body': '🙂 café\n' * 200}])
        first = list(project('comments', payload, policy))
        self.assertEqual(first, list(project('comments', payload, policy)))
        self.assertGreater(len(first), 1)
        for locator, text in first:
            self.assertEqual(text, reproduce(payload, locator))
            self.assertLessEqual(len(text.encode('utf-8')), 256)
            self.assertEqual(locator['pointer'], '/0/body')
            self.assertLessEqual(locator['line_end'] - locator['line_start'], 3)
        self.assertEqual(first[0][0]['start'], 0)
        self.assertEqual(first[-1][0]['end'], len(('🙂 café\n' * 200).encode('utf-8')))

    def test_diff_file_hunk_boundaries_are_not_repositioned(self):
        payload = 'diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+🙂 café\n@@ -3 +3 @@\n-b\n+c\ndiff --git a/b.py b/b.py\n@@ -1 +1 @@\n-d\n+e\n'
        projected = list(project('diff', payload, ProjectionPolicy()))
        self.assertEqual(len(projected), 5)
        self.assertEqual([locator['field'] for locator, _ in projected], ['file_header', 'hunk', 'hunk', 'file_header', 'hunk'])
        self.assertEqual([locator['filename'] for locator, _ in projected], ['a.py', 'a.py', 'a.py', 'b.py', 'b.py'])
        self.assertEqual(''.join((t for _, t in projected)), payload)
        for locator, text in projected:
            self.assertEqual(text, reproduce(payload, locator))
            self.assertEqual(payload.encode('utf-8')[locator['start']:locator['end']].decode('utf-8'), text)

    def test_structural_locator_never_adopts_nearby_text(self):
        payload = canonical([{'body': 'café'}])
        locator, _ = next(project('comments', payload, ProjectionPolicy()))
        with self.assertRaises(ValueError):
            reproduce(payload, {**locator, 'start': 4})
        with self.assertRaises((KeyError, IndexError)):
            reproduce(payload, {**locator, 'pointer': '/1/body'})

class ExpandedRetrievalTests(unittest.TestCase):

    def test_progressive_read_extends_past_index_chunk_without_losing_source_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'cache'
            manifest, _ = make_cache(root, count=1, repeat=400)
            snapshot = manifest['snapshot_id']
            source = TriageCache(root)
            database = root.parent / 'reposition/search.sqlite'
            CacheIndex.build(source, database, snapshot=snapshot, policy=ProjectionPolicy(max_bytes=256, overlap_bytes=16))
            with CacheIndex(database) as index:
                result = index.query(source, 'café', snapshot=snapshot, components=('comments',), max_snippets_per_item=1)
                unit = result['items'][0]['fragments'][0]['unit_id']
                page = index.retrieve(source, (unit,), snapshot=snapshot, checkpoint=result['checkpoint'], fragment_bytes=1000, byte_offset=0)
                fragment = page['items'][0]['fragments'][0]
                self.assertGreater(len(fragment['excerpt']['text'].encode()), 256)
                self.assertLessEqual(len(fragment['excerpt']['text'].encode()), 1000)
                self.assertTrue(fragment['continuation'])
                next_page = index.retrieve(source, (unit,), snapshot=snapshot, checkpoint=result['checkpoint'], fragment_bytes=1000, byte_offset=fragment['continuation']['byte_offset'])
                self.assertEqual(next_page['items'][0]['fragments'][0]['excerpt']['start'], fragment['excerpt']['end'])
                with self.assertRaisesRegex(ValueError, 'divides UTF-8'):
                    index.retrieve(source, (unit,), snapshot=snapshot, checkpoint=result['checkpoint'], byte_offset=fragment['excerpt']['text'].encode().index('🙂'.encode()) + 1)

# Newly authored product service integration tests, Apache-2.0.
from trio_triage.storage import Store
from trio_triage.evidence import EvidenceService
from trio_triage.search import SearchService
from trio_triage.errors import TrioError

class ProductEvidenceSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/"home");self.store.init()
        self.ev=EvidenceService(self.store)
        self.dataset=self.ev.enroll(dict(host="github.com",repository_id=42,full_name="example/triage",visibility="public",observed_at=END))["dataset"]
        self.incoming=Path(self.temp.name)/"incoming"
        self.manifest,self.donor_corpus=make_cache(self.incoming,count=4,repeat=30)
        self.snapshot=self.ev.import_cache(self.dataset,self.incoming)["snapshots"][0]
        self.search=SearchService(self.store);self.search.build(self.dataset,self.snapshot)

    def query(self,query="café",**kw):
        return self.search.query(self.dataset,self.snapshot,query,max_snippets_per_item=1,**kw)

    def ref(self):return self.query(components=("comments",),limit=1)["items"][0]["fragments"][0]["ref"]

    def state_bytes(self):
        return {str(p.relative_to(self.store.root)):p.read_bytes() for p in self.store.root.rglob("*") if p.is_file()}

    def test_complete_product_wire_budget_and_decoded_utf8_refs(self):
        for maximum in (6000,12000,25000):
            result=self.query(max_bytes=maximum,fragment_bytes=80)
            wire=(canonical(result)+"\n").encode()
            self.assertEqual(len(wire),result["budget"]["used_bytes"])
            self.assertLessEqual(len(wire),maximum)
            for item in result["items"]:
                for fragment in item["fragments"]:
                    ref=fragment["ref"];actual=self.ev.resolve_ref(ref)
                    self.assertEqual(actual["text"],fragment["excerpt"]["text"])
                    self.assertEqual(ref["locator"]["start"],fragment["excerpt"]["start"])
                    self.assertEqual(ref["locator"]["end"],fragment["excerpt"]["end"])

    def test_refs_and_expansion_survive_index_deletion(self):
        ref=self.ref();self.search._path(self.dataset,self.snapshot).unlink()
        self.assertTrue(self.ev.resolve_ref(ref)["verified"])
        result=self.search.retrieve(ref,window=500)
        self.assertTrue(result["items"][0]["fragments"][0]["verified"])
        self.assertEqual((canonical(result)+"\n").encode().__len__(),result["budget"]["used_bytes"])
        with self.assertRaises(TrioError) as error:self.query()
        self.assertEqual(error.exception.code,"INDEX_MISSING")

    def test_reads_do_not_modify_state_and_missing_store_not_created(self):
        before=self.state_bytes();self.query();self.search.retrieve(self.ref());self.ev.datasets();self.ev.snapshots(self.dataset)
        self.assertEqual(before,self.state_bytes())
        absent=Path(self.temp.name)/"absent"
        with self.assertRaises(TrioError):EvidenceService(Store(absent))
        self.assertFalse(absent.exists())

    def test_all_nine_components_integrated(self):
        queries={"summary":"suspend","comments":"café","files":"terminal","diff":"café","reviews":"Alternative","review_comments":"another cause","checks":"Synthetic","closing_issues":"issues","timeline":"observation"}
        for component,query in queries.items():
            with self.subTest(component=component):
                output=self.query(query,components=(component,))
                self.assertTrue(output["items"])
                self.ev.resolve_ref(output["items"][0]["fragments"][0]["ref"])

    def test_literal_is_explicit_and_offline_without_index(self):
        self.search._path(self.dataset,self.snapshot).unlink()
        out=self.query("terminal fails after suspend",mode="literal")
        self.assertTrue(out["items"]);self.assertEqual(out["diagnostics"]["method"],"literal")
        self.assertTrue(out["items"][0]["fragments"][0]["problems"])
        with self.assertRaises(TrioError):self.query()

    def test_cursors_bind_budgets_query_and_index_publication(self):
        first=self.query(limit=1);cursor=first["continuation"];self.assertTrue(cursor)
        for change in ({"max_bytes":25000},{"fragment_bytes":80},{"limit":2}):
            with self.subTest(change=change),self.assertRaises(TrioError) as error:self.query(limit=change.get("limit",1),cursor=cursor,**{k:v for k,v in change.items() if k!="limit"})
            self.assertEqual(error.exception.code,"CHECKPOINT_CHANGED")
        self.search.build(self.dataset,self.snapshot,replace=True)
        with self.assertRaises(TrioError):self.query(limit=1,cursor=cursor)

    def test_corrupt_source_index_and_utf8_boundary_refuse(self):
        ref=self.ref();bad=copy.deepcopy(ref);bad["locator"]["pointer"]="/999/body"
        with self.assertRaises(TrioError) as error:self.ev.resolve_ref(bad)
        self.assertEqual(error.exception.code,"EVIDENCE_CORRUPT")
        p=self.ev.path(self.dataset,"evidence","objects",contract.object_name(ref["object"]))
        p.write_bytes(b"synthetic corrupt source")
        with self.assertRaises(TrioError) as error:self.query()
        self.assertEqual(error.exception.code,"EVIDENCE_CORRUPT")
        db=self.search._path(self.dataset,self.snapshot);db.write_bytes(b"synthetic corrupt index")
        with self.assertRaises(TrioError) as error:self.query()
        self.assertEqual(error.exception.code,"INDEX_CORRUPT")

    def test_frozen_corpus_checkpoint_and_nonexpansion(self):
        plan=self.ev.freeze_corpus(self.dataset,self.snapshot)
        corpus={"corpus":plan["corpus"]};self.search.build(self.dataset,corpus)
        source=self.ev.source(self.dataset);selected=source.select(corpus=plan["corpus"])
        state_path=self.ev.path(self.dataset,"evidence","corpora",plan["corpus"]+".state.json")
        state=json.loads(state_path.read_text());state["updated_at"]="2026-09-28T12:00:00Z";state.pop("checksum");state_path.write_text(canonical(sealed(state)))
        with self.assertRaises(TrioError) as error:self.search.query(self.dataset,corpus,"terminal")
        self.assertEqual(error.exception.code,"CHECKPOINT_CHANGED")
        self.assertEqual([m["identity"] for m in source.select(corpus=plan["corpus"]).members],[m["identity"] for m in selected.members])

    def test_import_strict_checks_and_source_unchanged(self):
        before=evidence_bytes(self.incoming);self.ev.import_cache(self.dataset,self.incoming)
        self.assertEqual(before,evidence_bytes(self.incoming))
        cache=self.incoming/"cache.json";metadata=json.loads(cache.read_text());metadata["repository"]["database_id"]=999;cache.write_text(canonical(metadata))
        with self.assertRaises(TrioError):self.ev.import_cache(self.dataset,self.incoming)
        self.assertEqual(self.ev.scope(self.dataset)["repository_id"],42)

    def test_resources_preserve_prior_evidence(self):
        before=self.state_bytes();self.store.config["verified_max_bytes"]=1
        with self.assertRaises(TrioError) as error:self.ev.import_cache(self.dataset,self.incoming)
        self.assertEqual(error.exception.code,"RESOURCE_LIMIT");self.assertEqual(before,self.state_bytes())
        self.store.config["projection_max_units"]=1;index=self.search._path(self.dataset,self.snapshot).read_bytes()
        with self.assertRaises(TrioError):self.search.build(self.dataset,self.snapshot,replace=True)
        self.assertEqual(index,self.search._path(self.dataset,self.snapshot).read_bytes())

    def test_capture_discussion_page_jobs_budget_partial_and_public_scope(self):
        class Read:
            def get(inner,path):
                if path=="/repos/example/triage":return {"id":42,"full_name":"example/triage","private":False}
                if "comments?" in path:return [{"id":1,"body":"Synthetic discussion café"}]
                return {"id":1001,"number":1,"node_id":"issue_synthetic_1","state":"open","title":"Synthetic discussion","updated_at":START}
        result=self.ev.capture(self.dataset,"issue",1,Read())
        self.assertTrue(result["coverage"]["complete"]);self.assertLessEqual(result["requests"],100)
        partial=self.ev.capture(self.dataset,"issue",1,Read(),budget=2)
        self.assertFalse(partial["coverage"]["complete"])
        source=self.ev.snapshot(self.dataset,partial["snapshot"])
        self.assertNotEqual(source["items"][0]["components"]["comments"]["status"],"complete")
        class Private(Read):
            def get(inner,path):return {"id":42,"full_name":"example/triage","private":True}
        with self.assertRaises(TrioError) as error:self.ev.capture(self.dataset,"issue",1,Private())
        self.assertEqual(error.exception.code,"PUBLIC_REPO_REQUIRED")
        with self.assertRaises(TrioError):self.ev.require_shareable(self.dataset)

    def test_exact_scope_integer_contract_and_reenrollment(self):
        base=self.ev.scope(self.dataset)
        for field,value in (("repository_id",True),("repository_id",42.0),("format_version",True),("format_version",1.0)):
            with self.subTest(field=field,value=value),self.assertRaises(TrioError):self.ev.enroll(dict(base,**{field:value}))
        newer=dict(base,observed_at="2026-09-28T00:00:00Z")
        self.assertEqual(self.ev.enroll(newer)["dataset"],self.dataset)

    def test_retrieve_shortens_complete_utf8_response(self):
        ref=self.ref();out=self.search.retrieve(ref,window=4096,max_bytes=3000)
        fragment=out["items"][0]["fragments"][0]
        self.assertLessEqual(out["budget"]["used_bytes"],3000)
        self.assertEqual(self.ev.resolve_ref(fragment["ref"])["text"],fragment["excerpt"]["text"])

    def test_cli_retrieval_continues_verified_utf8_source(self):
        from trio_triage.catalog import catalog
        from trio_triage.cli import main, parser
        from trio_triage.storage import atomic_json

        ref = self.ref()
        refpath = Path(self.temp.name) / "selected-ref.json"
        atomic_json(refpath, ref)
        before = self.state_bytes()

        def page(*options):
            stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
            with (
                contextlib.redirect_stdout(stream),
                patch("socket.socket", side_effect=AssertionError("offline retrieval")),
            ):
                code = main(
                    [
                        "--home",
                        str(self.store.root),
                        "retrieve",
                        "--ref",
                        str(refpath),
                        "--window",
                        "80",
                        "--json",
                        *options,
                    ]
                )
            stream.flush()
            return code, json.loads(stream.buffer.getvalue())

        code, first = page()
        self.assertEqual(code, 0)
        prior = first["items"][0]["fragments"][0]
        code, second = page("--byte-offset", str(prior["continuation"]["byte_offset"]))
        self.assertEqual(code, 0)
        following = second["items"][0]["fragments"][0]
        self.assertEqual(following["excerpt"]["start"], prior["excerpt"]["end"])
        self.assertNotEqual(
            following["ref"]["excerpt_sha256"], prior["ref"]["excerpt_sha256"]
        )
        for response in (first, second):
            fragment = response["items"][0]["fragments"][0]
            self.assertEqual(
                self.ev.resolve_ref(fragment["ref"])["text"],
                fragment["excerpt"]["text"],
            )
            self.assertEqual(
                len((canonical(response) + "\n").encode()),
                response["budget"]["used_bytes"],
            )
        source = self.ev.resolve_ref(ref)["text"].encode()
        # The selected excerpt contains a two-byte accented character.
        split = (
            ref["locator"]["start"]
            - ref["locator"]["boundary_start"]
            + source.index("é".encode())
            + 1
        )
        for invalid in (
            -1,
            split,
            ref["locator"]["boundary_end"] - ref["locator"]["boundary_start"],
        ):
            code, error = page("--byte-offset", str(invalid))
            self.assertNotEqual(code, 0)
            self.assertEqual(error["error"]["code"], "EVIDENCE_CORRUPT")
        retrieve = next(
            x for x in catalog(parser())["leaves"] if x["command"] == "retrieve"
        )
        self.assertTrue(
            any("--byte-offset" in x["flags"] for x in retrieve["arguments"])
        )
        self.assertEqual(before, self.state_bytes())

    def test_index_admission_counts_overlapping_roots_once(self):
        self.store.config["index_max_bytes"] = 1048576
        for root in (
            self.store.root / "cache",
            Path(self.temp.name) / "external-cache",
            Path(self.temp.name),
        ):
            with self.subTest(cache=root):
                self.store.cache_root = root
                if root == self.store.root / "cache":
                    usage = self.ev._usage(self.store.root)
                elif root == Path(self.temp.name):
                    usage = self.ev._usage(root)
                else:
                    usage = self.ev._usage(self.store.root) + self.ev._usage(root)
                ceiling = (
                    usage
                    + self.store.config["index_max_bytes"]
                    + self.store.config["reserve_bytes"]
                )
                self.store.config["state_max_bytes"] = ceiling
                self.search.build(self.dataset, self.snapshot, replace=True)
                path = self.search._path(self.dataset, self.snapshot)
                original = path.read_bytes()
                usage = self.ev._usage_union(root, self.store.root)
                self.store.config["state_max_bytes"] = (
                    usage
                    + self.store.config["index_max_bytes"]
                    + self.store.config["reserve_bytes"]
                    - 1
                )
                with self.assertRaises(TrioError) as error:
                    self.search.build(self.dataset, self.snapshot, replace=True)
                self.assertEqual(error.exception.code, "RESOURCE_LIMIT")
                self.assertEqual(original, path.read_bytes())

    def test_overlapping_usage_still_refuses_symlinks(self):
        link = Path(self.temp.name) / "cache-link"
        link.symlink_to(self.store.root / "cache", target_is_directory=True)
        with self.assertRaises(TrioError) as error:
            self.ev._usage_union(self.store.root, link)
        self.assertEqual(error.exception.code, "SCOPE_DENIED")

    def test_sensitive_output_and_cursor_do_not_skip_unemitted_safe_item(self):
        # Direct boundary fixture controls ranking so the sensitive third item does not skip the second.
        query=self.query(max_bytes=25000);items=query["items"][:3]
        self.assertEqual(len(items),3)
        items[2]["title"]="api"+"_"+"key"+"="+"SYNTHETICCANARYVALUE123456"
        result=dict(query,items=items,diagnostics=dict(query["diagnostics"],ranked_groups=3,offset=0))
        full=self.search._bound(copy.deepcopy(result),25000,"token",0)
        one=copy.deepcopy(result);one["items"]=one["items"][:1];one["diagnostics"]["ranked_groups"]=3
        measure=self.search._bound(one,25000,"token",0)["budget"]["used_bytes"]
        bounded=self.search._bound(result,measure+100,"token",0)
        self.assertEqual(len(bounded["items"]),1)
        continuation=json.loads(base64.urlsafe_b64decode(bounded["continuation"]))
        self.assertEqual(continuation["offset"],1)
        self.assertNotIn("SYNTHETICCANARYVALUE",canonical(full))

    def test_optional_token_budget_measures_full_response(self):
        class OfflineTokenizer:
            name="synthetic-byte-test"
            def encode(self,text):return list(text.encode())
        search=SearchService(self.store,tokenizer=OfflineTokenizer())
        result=search.query(self.dataset,self.snapshot,"terminal",max_tokens=12000,max_bytes=25000,max_snippets_per_item=1)
        self.assertEqual(result["token_budget"]["used"],len((canonical(result)+"\n").encode()))
        self.assertLessEqual(result["token_budget"]["used"],12000)
        with self.assertRaises(TrioError) as error:self.query(max_tokens=1000)
        self.assertEqual(error.exception.code,"TOKENIZER_UNAVAILABLE")

class ProductCaptureProfilesTests(unittest.TestCase):
    setUp=ProductEvidenceSearchTests.setUp
    query=ProductEvidenceSearchTests.query
    ref=ProductEvidenceSearchTests.ref

    # Use independent synthetic read transport; no source network/credential path.
    def read_transport(self):
        repo={"id":42,"node_id":"R_synthetic","full_name":"example/triage","private":False}
        patch="@@ -1 +1 @@\n-old\n+resume café 🙂\n"
        row={"filename":"src/example.py","status":"modified","patch":patch,"additions":1,"deletions":1}
        summary={"id":1002,"node_id":"pr_synthetic_2","number":2,"state":"open","merged":False,"body":"Synthetic PR","title":"Resume café","updated_at":START,"comments":0,"changed_files":1,"additions":1,"deletions":1,"review_comments":0,"head":{"sha":"b"*40,"repo":repo},"base":{"sha":"a"*40,"repo":repo}}
        class Read:
            calls=[]
            def get(inner,path):
                inner.calls.append(path)
                if path=="/repos/example/triage":return copy.deepcopy(repo)
                if path=="/repos/example/triage/pulls/2":return copy.deepcopy(summary)
                if "/files?" in path:return [copy.deepcopy(row)]
                if "/check-suites/" in path:return {"total_count":1,"check_runs":[{"id":601,"name":"Synthetic check","head_sha":"b"*40,"check_suite":{"id":600},"conclusion":"success"}]}
                if "/check-suites?" in path:return {"total_count":1,"check_suites":[{"id":600,"head_sha":"b"*40,"status":"completed"}]}
                if "/statuses?" in path:return [{"id":602,"context":"Synthetic status","state":"success"}]
                return []
            def diff(inner,path):
                inner.calls.append(path+" [diff]")
                return "diff --git a/src/example.py b/src/example.py\n--- a/src/example.py\n+++ b/src/example.py\n"+patch
            def closing_page(inner,node_id,after):
                inner.calls.append("fixed ClosingIssues")
                return {"id":"pr_synthetic_2","number":2,"url":"https://github.com/example/triage/pull/2","repository":{"id":"R_synthetic","nameWithOwner":"example/triage","isPrivate":False},"updatedAt":START,"baseRefOid":"a"*40,"headRefOid":"b"*40,"closingIssuesReferences":{"totalCount":1,"pageInfo":{"hasNextPage":False,"endCursor":None},"nodes":[{"id":"I_LINK","number":1,"url":"https://github.com/example/triage/issues/1","state":"OPEN","updatedAt":START,"repository":{"id":"R_synthetic","nameWithOwner":"example/triage","isPrivate":False}}]}}
        return Read()

    def test_every_required_profile_captures_compatible_search_sources(self):
        for profile in ("discussion","pr-context","pr-code","pr-comparison","backlog"):
            with self.subTest(profile=profile):
                transport=self.read_transport();result=self.ev.capture(self.dataset,"pr",2,transport,profile=profile)
                self.assertTrue(result["coverage"]["complete"],result["coverage_detail"])
                self.search.build(self.dataset,result["snapshot"])
                self.assertTrue(self.search.query(self.dataset,result["snapshot"],"café")["items"])
                if profile=="pr-comparison":
                    for component,query in (("diff","café"),("checks","Synthetic"),("closing_issues","issues")):
                        found=self.search.query(self.dataset,result["snapshot"],query,components=(component,))
                        self.assertTrue(found["items"])

    def test_production_graphql_envelope_captures_comparison_closing_issues(self):
        import io
        from unittest.mock import patch
        from trio_triage.transport import ReadTransport
        from trio_triage.evidence.read_contract import CLOSING_QUERY
        fixture=self.read_transport();transport=ReadTransport();transport.get=fixture.get;transport.diff=fixture.diff
        node=fixture.closing_page("pr_synthetic_2",None);requests=[]
        class Opener:
            def open(inner,request,timeout):
                requests.append(request)
                return io.BytesIO(json.dumps({"data":{"node":node,"rateLimit":{"remaining":4999}}}).encode())
        with patch("urllib.request.build_opener",return_value=Opener()):
            result=self.ev.capture(self.dataset,"pr",2,transport,profile="pr-comparison")
        self.assertTrue(result["coverage"]["complete"],result["coverage_detail"])
        self.assertEqual(len(requests),1);request=requests[0]
        self.assertEqual(request.full_url,"https://api.github.com/graphql");self.assertEqual(request.get_method(),"POST")
        self.assertFalse(request.has_header("Authorization"))
        self.assertEqual(json.loads(request.data),{"query":CLOSING_QUERY,"variables":{"id":"pr_synthetic_2","after":None}})
        self.search.build(self.dataset,result["snapshot"])
        self.assertTrue(self.search.query(self.dataset,result["snapshot"],"issues",components=("closing_issues",))["items"])
    def test_graphql_errors_and_malformed_envelopes_fail_without_remote_payload(self):
        from unittest.mock import patch
        from trio_triage.transport import ReadTransport
        transport=ReadTransport();node=self.read_transport().closing_page("pr_synthetic_2",None)
        for response in ([],{}, {"data":{}},{"data":{"node":{}}},{"data":{"node":node},"errors":[{"message":"NONLIVE_PRIVATE_ERROR_CANARY"}]},{"data":{"node":node},"errors":{}}):
            with self.subTest(response=response),patch.object(transport,"_special",return_value=response),self.assertRaises(TrioError) as error:transport.closing_page("pr_synthetic_2")
            self.assertEqual(error.exception.code,"TRANSPORT_FAILURE");self.assertNotIn("CANARY",str(error.exception))
        with patch.object(transport,"_special",return_value={"data":{"node":None}}):self.assertIsNone(transport.closing_page("pr_synthetic_2"))
        for error in ({"type":"RATE_LIMITED"},{"extensions":{"code":"RATE_LIMITED"}}):
            with patch.object(transport,"_special",return_value={"errors":[error]}),self.assertRaises(TrioError) as failure:transport.closing_page("pr_synthetic_2")
            self.assertEqual(failure.exception.code,"THROTTLED");self.assertEqual(failure.exception.retry_after,60)
    def test_private_head_refuses_before_code_request(self):
        transport=self.read_transport();original=transport.get
        def get(path):
            value=original(path)
            if path.endswith("/pulls/2"):value["head"]["repo"]["private"]=True
            return value
        transport.get=get
        with self.assertRaises(TrioError) as error:self.ev.capture(self.dataset,"pr",2,transport,profile="pr-code")
        self.assertEqual(error.exception.code,"PUBLIC_REPO_REQUIRED")
        self.assertFalse(any("files?" in p or "[diff]" in p for p in transport.calls))

    def test_shared_cooldown_is_durable_and_has_no_remote_error_payload(self):
        transport=self.read_transport();original=transport.get
        def get(path):
            if "comments?" in path:
                error=TrioError("THROTTLED");error.retry_after=600;raise error
            return original(path)
        transport.get=get
        result=self.ev.capture(self.dataset,"pr",2,transport)
        self.assertFalse(result["coverage"]["complete"])
        cooldown=list((self.store.root/"acquisition").glob("*.json"));self.assertTrue(cooldown)
        with self.assertRaises(TrioError) as error:self.ev.capture(self.dataset,"pr",2,self.read_transport())
        self.assertEqual(error.exception.code,"THROTTLED")
        self.assertNotIn("Authorization",cooldown[0].read_text())

    def test_currentness_stales_when_new_partial_observation_changes_revision(self):
        ref=self.ref();self.assertTrue(self.ev.is_current(ref))
        transport=self.read_transport();original=transport.get
        def get(path):
            value=original(path)
            if path.endswith("/pulls/2"):value["updated_at"]="2026-09-29T00:00:00Z"
            return value
        transport.get=get
        self.ev.capture(self.dataset,"pr",2,transport,budget=6)
        # Select an original PR reference so newer failed/partial data cannot be hidden.
        result=self.query(components=("comments",),kind="pr",limit=10)
        prior=next(item for item in result["items"] if item["identity"]["number"]==2)["fragments"][0]["ref"]
        self.assertFalse(self.ev.is_current(prior));self.assertTrue(self.ev.resolve_ref(prior)["verified"])

    def test_corpus_run_retains_exact_members_and_invalidates_built_view(self):
        plan=self.ev.freeze_corpus(self.dataset,self.snapshot,scope="open-prs")
        selected={"corpus":plan["corpus"]};before=self.ev.source(self.dataset).select(**selected)
        self.search.build(self.dataset,selected)
        out=self.ev.run_corpus(self.dataset,plan["corpus"],self.read_transport(),budget=12)
        self.assertLessEqual(out["requests"],12)
        after=self.ev.source(self.dataset).select(**selected)
        self.assertEqual([m["identity"] for m in before.members],[m["identity"] for m in after.members])
        with self.assertRaises(TrioError) as error:self.search.query(self.dataset,selected,"terminal")
        self.assertEqual(error.exception.code,"CHECKPOINT_CHANGED")


class PinnedContractDifferentialTests(unittest.TestCase):
    def test_selected_public_donor_validator_function_asts_are_equal(self):
        # Both pinned donor validators had identical function ASTs; expected digests are public-source evidence.
        expected={'fields': 'fb4a02c4a6ef5fb69f300117b1daea371ccb2c82b16359672c4e825feb09dcf7', 'text': '299700e97fc88c55a48b8d25fe0bb247e3dfca22fee910845a1a89d44d53b5b6', 'natural': '67ea8c6b065a7c509cbf17d39a1dcb218cd4d0d35135db09d2312f7cd99506ca', 'timestamp': 'ac9bd2bd71d326d6b77a374872c9264fca6947f71f1f4a5928ce20283f4c18f9', 'version': 'eaa1b28903da66147335739d3edd5af8674aa03ee829163b5f1b8a34120ba147', 'stable_ids': 'b559640141d7d48f4deb016f9f09c362f53d417ae8d99cb9950f5d1ddeafe820', 'repository': 'a126f61b5f28005cbd9664a31f2a74e66a493bae236b8ac6e177ab42e037596d', 'validate_repository': 'dbbf553bb8ac7c9328a069923306aad77e049c82979aa93b76cff7aedf7778da', 'same_repository': 'd9cc2e8203bb9c963121735db2fb4b622b0a2a4a352f954282b863763a0519c9', 'validate_item': 'e436307698dca9577edacedc376fc09abc5b998b4f4cdf3a81d2c6dec06cac71', 'same_item': 'fbf2ace39cb8201151138b67de86c7de78d7b4332a63cf9cf4b6a6be30dc1f38', 'validate_revision': '27672f8abd6dad7e293e0ebbe60b71f3cb2dad77fad239a9fe946809cf521296', 'canonical': '8a42336c1401ec4e42c93c23e72093452fe3659e110958c1387077f9ba1d42fb', 'digest': '9a65b6388741b8c24ef21fffd470f620150087b67f39e7eef72fad3fce546c86', 'artifact_ref': 'ee72715ebef54b34aeb10647ddd5a640e670b767520f0379dfd2ae2e7a292737', 'reject_constant': 'b015d4992ffa2edc2d3ca20984615b12583cb8e467e0248cc6db4c9787e42b49', 'validate_ref': 'e01ee30e94ab547abf75051af5e87da74c362f5e73357906725dbbc80f095a94', 'object_name': 'cb0cb7e7999684d423d68cca23b5209a2ac18e5b6a1b76e4283521f67d531c6b', 'validate_component': '15a2b67c1a353283d5ffca0bd4aae0ac9dcea4ee3c742d48733fa86728aa49c4', 'validate_payload': 'db5a063c1690a2160f3073577b4d73cb8402c72ce21a2ddbc789bf3ce9080ed9', 'snapshot_id': 'a2e1f8b4a74438ab9897a056c910919729dad1bc343f84adfd7d6b3caed13dd4', 'seal_snapshot': '1cfe133d7b80cc6e95132daecbb4ed72e448df33174afc118a14dae72bed9f8e', 'validate_snapshot': '8d02e5a363a4ea2ed3506b7628d164185d193fc7b547b59984de108c3711a60b', 'component_problems': 'e45f8e076a4b43aa814db4c4605b32c35aacbcae62141e612aae4b66af65cc08', 'coverage': 'c8285b952586a9a7fdc6bb0bf6febbe0ed2d5a5e782036993a9cc18b014914b4'}
        import ast,inspect
        from trio_triage import contracts
        tree=ast.parse(inspect.getsource(contracts))
        actual={n.name:hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest() for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in expected}
        self.assertEqual(actual,expected)

class OfflineTokenizerBoundaryTests(unittest.TestCase):
    def test_explicit_encoding_and_missing_asset_do_not_resolve_network(self):
        from trio_triage.search.tokenizer import load_offline_tokenizer
        with patch("urllib.request.urlopen",side_effect=AssertionError("network forbidden")):
            with self.assertRaises(TrioError) as error:load_offline_tokenizer("unknown","synthetic-missing")
            self.assertEqual(error.exception.code,"INVALID_ARGUMENT")
            with self.assertRaises(TrioError) as error:load_offline_tokenizer("cl100k_base","synthetic-missing")
            self.assertEqual(error.exception.code,"TOKENIZER_UNAVAILABLE")

class EvidenceFaultRecoveryTests(unittest.TestCase):
    setUp=ProductEvidenceSearchTests.setUp
    def test_enrollment_failure_metadata_or_scope_has_no_unready_authoritative_scope(self):
        from trio_triage.evidence import service
        original=service.atomic_bytes
        for boundary in ("cache.json","scope.json"):
            scope=dict(host="github.com",repository_id=100 if boundary=="cache.json" else 101,full_name="example-org/example-repo",visibility="public",observed_at=END)
            dataset=contract.digest(canonical([scope["host"],scope["repository_id"],None]))
            def fail(path,raw):
                if path.name==boundary:raise OSError("synthetic fault")
                return original(path,raw)
            with patch.object(service,"atomic_bytes",side_effect=fail),self.assertRaises(OSError):self.ev.enroll(scope)
            self.assertFalse(self.ev.path(dataset,"scope.json").exists())
            self.assertNotIn(dataset,[d["dataset"] for d in self.ev.datasets()])
            self.assertEqual(self.ev.enroll(scope)["dataset"],dataset)
            self.assertEqual(self.ev.source(dataset).repository["database_id"],scope["repository_id"])

    def test_object_then_manifest_publication_fault_leaves_only_complete_unused_bytes(self):
        from trio_triage.evidence import service
        original=service.atomic_bytes
        for boundary in ("objects","snapshots"):
            manifest=copy.deepcopy(self.manifest);manifest.pop("snapshot_id")
            record=manifest["items"][0];desc=record["components"]["summary"]
            payload=json.loads(self.ev.source(self.dataset).object("summary",desc,"issue"));payload["title"]="Synthetic fault boundary "+boundary
            raw=canonical(payload);desc["object"]=contract.artifact_ref(raw)
            manifest=contract.seal_snapshot(manifest);filename=contract.object_name(desc["object"])
            def fail(path,value):
                if boundary in path.parts:raise OSError("synthetic fault")
                return original(path,value)
            with patch.object(service,"atomic_bytes",side_effect=fail),self.assertRaises(TrioError):self.ev.publish(self.dataset,manifest,{filename:raw})
            self.assertFalse(self.ev.path(self.dataset,"evidence","snapshots",manifest["snapshot_id"]+".json").exists())
            path=self.ev.path(self.dataset,"evidence","objects",filename)
            if path.exists():self.assertEqual(path.read_bytes(),raw.encode())
            self.ev.publish(self.dataset,manifest,{filename:raw})
            self.assertEqual(self.ev.source(self.dataset).manifest(manifest["snapshot_id"]),manifest)

    def test_mutable_saved_page_is_revalidated_without_overwriting_old_snapshot(self):
        class Read:
            body="first captured café"
            def get(inner,path):
                if path=="/repos/example/triage":return {"id":42,"full_name":"example/triage","private":False}
                if "comments?" in path:return [{"id":1,"body":inner.body}]
                return {"id":1001,"node_id":"issue_synthetic_1","number":1,"state":"open","updated_at":START,"comments":1}
        read=Read();first=self.ev.capture(self.dataset,"issue",1,read)
        old=self.ev.snapshot(self.dataset,first["snapshot"])
        read.body="edited captured café";second=self.ev.capture(self.dataset,"issue",1,read)
        new=self.ev.snapshot(self.dataset,second["snapshot"])
        first_ref=old["items"][0]["components"]["comments"]
        second_ref=new["items"][0]["components"]["comments"]
        self.assertNotEqual(first_ref["object"],second_ref["object"])
        self.assertIn("first captured",self.ev.source(self.dataset).object("comments",first_ref,"issue"))
        self.assertIn("edited captured",self.ev.source(self.dataset).object("comments",second_ref,"issue"))

class AcquisitionNamespaceTests(unittest.TestCase):
    setUp=ProductEvidenceSearchTests.setUp
    def test_authenticated_account_binding_is_checked_before_repository_reads(self):
        scope=dict(self.ev.scope(self.dataset),profile="github-account:100")
        enrolled=self.ev.enroll(scope)["dataset"]
        class Account:
            reads=[]
            def namespace(inner):return "github-account:200"
            def get(inner,path):inner.reads.append(path);raise AssertionError("repository must not be read")
        transport=Account()
        with self.assertRaises(TrioError) as error:self.ev.capture(enrolled,"issue",1,transport)
        self.assertEqual(error.exception.code,"IDENTITY_MISMATCH");self.assertFalse(transport.reads)
        class Anonymous(Account):
            token=None
            def namespace(inner):return None
        with self.assertRaises(TrioError):self.ev.capture(enrolled,"issue",1,Anonymous())
        with self.assertRaises(TrioError):self.ev.capture(self.dataset,"issue",1,Account())

    def test_account_namespace_not_environment_name_keys_cooldown(self):
        scope=dict(self.ev.scope(self.dataset),profile="github-account:100")
        enrolled=self.ev.enroll(scope)["dataset"]
        class Account:
            def __init__(inner,env):inner.profile=env
            def namespace(inner):return "github-account:100"
            def get(inner,path):
                if path=="/repos/example/triage":return {"id":42,"full_name":"example/triage","private":False}
                if "comments?" in path:
                    error=TrioError("THROTTLED");error.retry_after=600;raise error
                return {"id":1001,"number":1,"node_id":"issue_synthetic_1","state":"open","updated_at":START}
        self.ev.capture(enrolled,"issue",1,Account("SYNTHETIC_READ_A"))
        with self.assertRaises(TrioError) as error:self.ev.capture(enrolled,"issue",1,Account("SYNTHETIC_READ_B"))
        self.assertEqual(error.exception.code,"THROTTLED")
        self.assertEqual(len(list((self.store.root/"acquisition").glob("*.json"))),1)

class BoundedInventoryTests(unittest.TestCase):
    setUp=ProductEvidenceSearchTests.setUp
    def transport(self):
        class Inventory:
            def get(inner,path):
                if path=="/repos/example/triage":return {"id":42,"full_name":"example/triage","private":False}
                if "issues?state=open" in path:
                    return [{"id":3000+n,"number":n,"node_id":"I_SYNTHETIC_"+str(n),"state":"open","updated_at":START,"title":"Synthetic café inventory "+str(n),"html_url":"https://github.com/example/triage/issues/"+str(n)} for n in (10,11,12)]
                raise AssertionError("unexpected endpoint")
        return Inventory()

    def test_complete_inventory_and_limit_truncation_freeze_observed_members(self):
        for limit,complete,expected in ((10,True,[10,11,12]),(2,False,[10,11])):
            with self.subTest(limit=limit):
                out=self.ev.capture_inventory(self.dataset,self.transport(),limit=limit)
                self.assertEqual(out["inventory"]["pagination_complete"],complete)
                self.assertEqual(out["inventory"]["truncated"],not complete)
                plan=self.ev.freeze_corpus(self.dataset,out["snapshot"])
                self.assertEqual(plan["enumeration"]["live_enumeration_complete"],complete)
                self.assertEqual([m["identity"]["number"] for m in self.ev.source(self.dataset).select(corpus=plan["corpus"]).members],expected)
                self.search.build(self.dataset,out["snapshot"])
                self.assertTrue(self.search.query(self.dataset,out["snapshot"],"café")["items"])

    def test_budget_recheck_failure_keeps_partial_inventory_without_false_empty_claim(self):
        out=self.ev.capture_inventory(self.dataset,self.transport(),limit=10,budget=2)
        self.assertEqual(out["requests"],2);self.assertFalse(out["inventory"]["live_enumeration_complete"])
        self.assertFalse(out["coverage"]["complete"])
        self.assertEqual(len(self.ev.snapshot(self.dataset,out["snapshot"])["items"]),3)

    def test_explicit_combination_adds_no_unselected_member_and_no_live_enumeration_claim(self):
        source=self.ev.source(self.dataset);manifests=[]
        for record in self.manifest["items"][:2]:
            value={k:copy.deepcopy(v) for k,v in self.manifest.items() if k!="snapshot_id"};value["items"]=[record];value=contract.seal_snapshot(value)
            manifests.append(self.ev.publish(self.dataset,value,{})["snapshot"])
        out=self.ev.combine_snapshots(self.dataset,manifests)
        self.assertFalse(out["inventory"]["live_enumeration_complete"])
        self.assertEqual(len(self.ev.snapshot(self.dataset,out["snapshot"])["items"]),2)
        self.assertEqual(self.ev.combine_snapshots(self.dataset,list(reversed(manifests)))["snapshot"],out["snapshot"])
        plan=self.ev.freeze_corpus(self.dataset,out["snapshot"])
        self.assertEqual(len(self.ev.source(self.dataset).select(corpus=plan["corpus"]).members),2)

class AcquisitionCancellationTests(unittest.TestCase):
    setUp=ProductEvidenceSearchTests.setUp
    def test_cancelled_component_publishes_honest_partial_and_makes_no_later_reads(self):
        class Cancel:
            calls=[]
            def get(inner,path):
                inner.calls.append(path)
                if path=="/repos/example/triage":return {"id":42,"full_name":"example/triage","private":False}
                if "comments?" in path:raise KeyboardInterrupt()
                return {"id":1001,"number":1,"node_id":"issue_synthetic_1","state":"open","updated_at":START}
        read=Cancel();out=self.ev.capture(self.dataset,"issue",1,read)
        self.assertTrue(out["cancelled"]);self.assertFalse(out["coverage"]["complete"])
        self.assertEqual(len(read.calls),3);self.assertEqual(out["requests"],3)
        self.assertEqual(self.ev.snapshot(self.dataset,out["snapshot"])["items"][0]["components"]["comments"]["status"],"failed")

class PullInventoryIdentityTests(unittest.TestCase):
    setUp=ProductEvidenceSearchTests.setUp
    def transport(self,private_head=False):
        # The list endpoint returns an Issue ID; selected pull endpoint binds a different PR ID.
        stub=ProductCaptureProfilesTests.read_transport(self);original=stub.get
        def get(path):
            if "issues?state=open" in path:return [{"id":9002,"node_id":"ISSUE_OBJECT_9002","number":2,"state":"open","pull_request":{},"updated_at":START,"html_url":"https://github.com/example/triage/pull/2"}]
            value=original(path)
            if path.endswith("/pulls/2"):
                value["html_url"]="https://github.com/example/triage/pull/2"
                if private_head:value["head"]["repo"]["private"]=True;value["head"]["repo"]["full_name"]="synthetic/private-canary"
            return value
        stub.get=get;return stub

    def test_inventory_binds_pull_identity_so_frozen_corpus_capture_matches(self):
        out=self.ev.capture_inventory(self.dataset,self.transport())
        record=self.ev.snapshot(self.dataset,out["snapshot"])["items"][0]
        self.assertEqual(record["identity"]["database_id"],1002)
        self.assertNotEqual(record["identity"]["database_id"],9002)
        self.assertEqual(record["revision"]["head_sha"],"b"*40)
        plan=self.ev.freeze_corpus(self.dataset,out["snapshot"],scope="open-prs")
        run=self.ev.run_corpus(self.dataset,plan["corpus"],self.transport())
        self.assertEqual(run["status"],"finished")
        self.assertEqual(run["coverage"]["outcomes"],{"complete":1})

    def test_private_head_inventory_stores_no_rejected_raw_summary(self):
        before={p:p.read_bytes() for p in self.ev.path(self.dataset).rglob("*") if p.is_file()}
        with self.assertRaises(TrioError) as error:self.ev.capture_inventory(self.dataset,self.transport(private_head=True))
        self.assertEqual(error.exception.code,"PUBLIC_REPO_REQUIRED")
        after={p:p.read_bytes() for p in self.ev.path(self.dataset).rglob("*") if p.is_file()}
        self.assertEqual(before,after)
        self.assertNotIn("private-canary",str(error.exception))

class ProductCoverageDiagnosticsTests(unittest.TestCase):
    setUp=ProductEvidenceSearchTests.setUp
    def test_product_states_preserve_absent_missing_unrequested_and_temporal_stale(self):
        manifest=copy.deepcopy(self.manifest);record=manifest["items"][0];manifest["items"]=[record]
        record["components"]["comments"].update(status="unavailable",object=None,error="collection missing",received_count=None,pagination_complete=False)
        record["components"].pop("timeline");manifest["requested_components"].remove("timeline")
        manifest.pop("snapshot_id");manifest=contract.seal_snapshot(manifest)
        coverage=self.ev.coverage(manifest)
        self.assertEqual(coverage["statuses"]["missing"],1)
        self.assertEqual(coverage["statuses"]["not-requested"],1)
        self.assertEqual(coverage["statuses"]["stale"],1)
        self.assertEqual(coverage["statuses"]["not-applicable"],6)
        self.assertFalse(coverage["current_complete"])
        query=self.search.query(self.dataset,self.snapshot,"café")
        self.assertIn("statuses",query["coverage"])
        self.assertEqual(query["budget"]["used_bytes"],len((canonical(query)+"\n").encode()))
