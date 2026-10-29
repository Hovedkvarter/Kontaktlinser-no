"""Synthetic Git/event regression tests; no network, feeds or publication."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import site_changes


class ChangeGuard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous = Path.cwd()
        os.chdir(self.root)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        self.write('README.md', 'baseline')
        self.write('build.py', '# synthetic site input')
        self.base = self.commit()

    def tearDown(self):
        os.chdir(self.previous)
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, path, content='synthetic'):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-m', 'synthetic test')
        return self.git('rev-parse', 'HEAD')

    def push(self, before, after):
        return site_changes.classify('push', {'before': before, 'after': after})

    def test_documentation_only_and_empty_diff(self):
        for p in ['AGENTS.md', 'CLAUDE.md', 'docs/CONTINUOUS-LEARNING-OFFLINE.md',
                  '.claude/rules/local.md', 'docs/file with spaces.md', 'docs/æøå.md']:
            self.write(p)
        tip = self.commit()
        self.assertEqual(self.push(self.base, tip), (False, False))
        self.assertEqual(self.push(tip, tip), (False, False))

    def test_real_inputs_and_unknown_markdown_are_not_filtered(self):
        for p in ['build.py', 'site_generator/render_templates.py', 'site_content.json',
                  'products_meta.json', 'sources_config.json', 'feeds/new.csv',
                  'assets/image.webp', 'docs/audit.json', 'content/guide.md',
                  'new-public-page.md', '.github/workflows/pages.yml',
                  '.github/scripts/site_changes.py', 'robots.txt']:
            with self.subTest(path=p):
                self.assertFalse(site_changes.documentation(p))
        self.write('site_content.json')
        self.assertEqual(self.push(self.base, self.commit()), (True, True))

    def test_mixed_push_uses_all_commits_not_only_last(self):
        self.write('build.py', 'changed')
        self.commit()
        self.write('README.md', 'last commit is only docs')
        self.assertEqual(self.push(self.base, self.commit()), (True, True))

    def test_more_than_api_file_limit(self):
        for i in range(3100):
            self.write(f'docs/{i:04}.md')
        self.write('zzz-site.json')
        self.assertEqual(self.push(self.base, self.commit()), (True, True))

    def test_deleted_site_and_renamed_site_to_docs(self):
        (self.root / 'build.py').rename(self.root / 'README-site.md')
        self.assertEqual(self.push(self.base, self.commit()), (True, True))
        self.git('reset', '--hard', self.base)
        (self.root / 'build.py').unlink()
        self.assertEqual(self.push(self.base, self.commit()), (True, True))

    def test_rename_into_allowed_docs_still_includes_old_path(self):
        (self.root / 'docs').mkdir()
        (self.root / 'build.py').rename(self.root / 'docs/build.md')
        self.assertEqual(self.push(self.base, self.commit()), (True, True))

    def test_documentation_delete_and_rename(self):
        (self.root / 'README.md').rename(self.root / 'CLAUDE.md')
        tip = self.commit()
        self.assertEqual(self.push(self.base, tip), (False, False))
        (self.root / 'CLAUDE.md').unlink()
        self.assertEqual(self.push(tip, self.commit()), (False, False))

    def test_pull_request_uses_merge_base_and_never_operates(self):
        self.git('checkout', '-b', 'docs')
        self.write('AGENTS.md')
        head = self.commit()
        self.git('checkout', 'main')
        self.write('build.py', 'unrelated main change')
        base = self.commit()
        event = {'pull_request': {'base': {'sha': base}, 'head': {'sha': head}}}
        self.assertEqual(site_changes.classify('pull_request', event), (False, False))
        self.git('checkout', 'docs')
        self.write('site_content.json')
        event['pull_request']['head']['sha'] = self.commit()
        self.assertEqual(site_changes.classify('pull_request', event), (True, False))

    def test_force_push_compares_old_and_new_trees(self):
        self.write('build.py', 'old pushed version')
        old = self.commit()
        self.git('reset', '--hard', self.base)
        self.write('AGENTS.md')
        self.assertEqual(self.push(old, self.commit()), (True, True))

    def test_merge_commit_compares_previous_main(self):
        self.git('checkout', '-b', 'docs')
        self.write('AGENTS.md')
        self.commit()
        self.git('checkout', 'main')
        self.git('merge', '--no-ff', 'docs', '-m', 'synthetic merge')
        self.assertEqual(self.push(self.base, self.git('rev-parse', 'HEAD')), (False, False))

    def test_manual_and_schedule_keep_existing_operational_behavior(self):
        for event in ['schedule', 'workflow_dispatch']:
            self.assertEqual(site_changes.classify(event, {}), (True, True))

    def test_new_branch_keeps_initial_build(self):
        self.assertEqual(site_changes.classify('push', {
            'created': True, 'before': '0' * 40, 'after': self.base,
        }), (True, True))

    def test_invalid_or_missing_history_stops_instead_of_silently_skipping(self):
        for before in [None, '0' * 40, 'f' * 40, '--help', 'not-a-sha']:
            with self.subTest(before=before), self.assertRaises((ValueError, subprocess.CalledProcessError)):
                self.push(before, self.base)
        with self.assertRaises(ValueError):
            site_changes.classify('unknown-event', {})

    def test_cli_output_and_failure_no_operational_output(self):
        self.write('AGENTS.md')
        tip = self.commit()
        event = self.root / 'event.json'
        output = self.root / 'output.txt'
        env = dict(os.environ, GITHUB_EVENT_NAME='push', GITHUB_EVENT_PATH=str(event), GITHUB_OUTPUT=str(output))
        for before, expected_return in [(self.base, 0), ('0' * 40, 1)]:
            event.write_text(json.dumps({'before': before, 'after': tip}))
            output.write_text('')
            result = subprocess.run([sys.executable, site_changes.__file__], env=env, capture_output=True)
            self.assertEqual(result.returncode, expected_return)
            self.assertEqual(output.read_text(), 'site_changed=false\noperational=false\n' if expected_return == 0 else '')


class WorkflowWiring(unittest.TestCase):
    def test_existing_tests_remain_and_operational_gate_is_wired(self):
        root = Path(__file__).resolve().parents[2]
        workflows = root / '.github/workflows'
        path = workflows / 'pages.yml'
        if path.exists():
            text = path.read_text()
            self.assertIn("if: needs.test.outputs.operational == 'true'", text)
            self.assertIn('operational: ${{ steps.changes.outputs.operational }}', text)
            self.assertIn('python -m unittest discover -s tests -v', text)
            self.assertIn('needs: build', text)
            for name in ['category-preview.yml', 'product-preview.yml']:
                preview = (workflows / name).read_text()
                self.assertIn("- name: Build real catalogue\n        if: steps.changes.outputs.operational == 'true'", preview)
                self.assertIn("- if: steps.changes.outputs.operational == 'true'\n        uses: actions/upload-pages-artifact@", preview)
                self.assertIn('fetch-depth: 0', preview)
        else:
            text = (workflows / 'build-and-deploy.yml').read_text()
            self.assertEqual(text.count("if: steps.changes.outputs.operational == 'true'"), 2)
            self.assertEqual(text.count("if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"), 3)
            self.assertIn('python3 -m unittest test_store_price_history', text)
            self.assertIn('node --test tests/test_search.cjs', text)
            self.assertIn('python3 -m unittest test_search_rendering', text)
            self.assertIn('python3 site_generator/validate_build.py', text)
            self.assertIn("steps.changes.outputs.site_changed == 'true' && secrets.CHILLOUT_READ_KEY || ''", text)
            discovery = (workflows / 'feed-discovery.yml').read_text()
            self.assertIn("if: needs.test.outputs.operational == 'true'", discovery)
            self.assertIn('python -m unittest test_feed_discovery -v', discovery)
        self.assertIn('fetch-depth: 0', text)
        self.assertIn('id: changes', text)
        self.assertIn('python .github/scripts/site_changes.py', text)
        self.assertNotIn('paths-ignore:', text)


if __name__ == '__main__':
    unittest.main()
