import base64
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
DIGEST = 'sha256:' + 'a' * 64
decode_kubeconfig = runpy.run_path(str(ROOT / 'scripts/deploy-helm.py'))['decode_kubeconfig']


def render(*args):
    return subprocess.run(
        ['helm', 'template', 'hievents', str(ROOT / 'helm'), '--namespace', 'hievents', *args],
        capture_output=True, text=True,
    )


class ChartTests(unittest.TestCase):
    def test_decodes_kubeconfig(self):
        config = 'apiVersion: v1\nkind: Config\nclusters: []\n'
        encoded = base64.b64encode(config.encode()).decode()
        for value in (encoded, '\n'.join(encoded[i:i + 16] for i in range(0, len(encoded), 16)) + '\n'):
            with self.subTest(value=value):
                self.assertEqual(decode_kubeconfig(value), config)

    def test_rejects_invalid_kubeconfig_without_disclosing_input(self):
        for value in ('', ' \n', 'not-base64!', 'apiVersion: v1\nkind: Config\n',
                      'YQ', base64.b64encode(b'\xff').decode(),
                      base64.b64encode(b'\x00').decode(), base64.b64encode(b'  ').decode()):
            with self.subTest(value=value):
                with self.assertRaises(SystemExit) as error:
                    decode_kubeconfig(value)
                self.assertEqual(str(error.exception),
                                 'Invalid LINODE_KUBECONFIG: expected base64-encoded UTF-8 kubeconfig YAML.')

    def test_chart(self):
        result = render('--set', f'image.digest={DIGEST}')
        self.assertEqual(result.returncode, 0, result.stderr)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        self.assertEqual(len(docs), 9)
        self.assertFalse(any(d['kind'] == 'Secret' for d in docs))
        app = next(d for d in docs if d['kind'] == 'Deployment')
        self.assertEqual(app['spec']['replicas'], 1)
        self.assertEqual(app['spec']['strategy']['type'], 'Recreate')
        pod = app['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertTrue(pod['containers'][0]['image'].endswith('@' + DIGEST))
        self.assertEqual(pod['containers'][0]['envFrom'][1]['secretRef']['name'], 'hievents-runtime')
        self.assertEqual(pod['containers'][0]['envFrom'][2]['secretRef']['name'], 'hievents-mail')
        ingress = next(d for d in docs if d['kind'] == 'Ingress')
        self.assertEqual(ingress['spec']['rules'][0]['host'], 'admin.elementafestival.com')
        self.assertEqual(ingress['spec']['tls'][0]['hosts'], ['admin.elementafestival.com'])
        config = next(d for d in docs if d['kind'] == 'ConfigMap')['data']
        self.assertEqual(config['APP_DISABLE_REGISTRATION'], 'true')
        self.assertEqual(config['VITE_API_URL_CLIENT'], 'https://admin.elementafestival.com/api')
        self.assertEqual(config['QUEUE_CONNECTION'], 'redis')
        self.assertEqual(config['MAIL_MAILER'], 'smtp')
        self.assertEqual(config['MAIL_HOST'], 'mail.smtp2go.com')
        self.assertEqual(config['MAIL_PORT'], '587')
        self.assertEqual(config['MAIL_ENCRYPTION'], 'tls')
        self.assertEqual(config['MAIL_VERIFY_PEER'], 'true')
        self.assertEqual(config['MAIL_AUTO_TLS'], 'true')
        self.assertEqual(config['MAIL_FROM_ADDRESS'], 'tickets@elementafestival.com')
        self.assertNotIn('MAIL_PASSWORD', config)
        self.assertNotIn('MAIL_USERNAME', config)
        for doc in docs:
            if doc['kind'] == 'StatefulSet':
                self.assertEqual(doc['spec']['volumeClaimTemplates'][0]['spec']['storageClassName'], 'linode-block-storage-retain')

    def test_rejects_mutable_or_missing_image(self):
        self.assertNotEqual(render().returncode, 0)
        self.assertNotEqual(render('--set', 'image.digest=latest').returncode, 0)

    def test_private_install(self):
        result = render('--set', f'image.digest={DIGEST}', '--set', 'ingress.enabled=false')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(d and d['kind'] == 'Ingress' for d in yaml.safe_load_all(result.stdout)))

    def test_startup_stops_on_migration_failure(self):
        with tempfile.TemporaryDirectory(prefix='hermes-verify-') as directory:
            php = Path(directory) / 'php'
            php.write_text('#!/bin/sh\nexit 1\n')
            php.chmod(0o700)
            startup = (ROOT / 'docker/all-in-one/scripts/startup.sh').read_text()
            startup = startup.replace('cd /app/backend', 'cd "' + directory + '"')
            result = subprocess.run(['sh'], input=startup, text=True, capture_output=True,
                                    env={**os.environ, 'PATH': directory + ':' + os.environ['PATH']})
            self.assertEqual(result.returncode, 1)
            self.assertIn('Migrations could not complete', result.stdout)
            self.assertNotIn('supervisord', result.stderr)

    def test_deploy_rejects_missing_credentials(self):
        env = {k: v for k, v in os.environ.items() if k not in
               ('LINODE_KUBECONFIG', 'GHCR_TOKEN', 'HIEVENTS_RUNTIME_JSON', 'IMAGE_DIGEST')}
        result = subprocess.run(['python3', str(ROOT / 'scripts/deploy-helm.py')],
                                env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing deployment secrets/settings:', result.stderr)

    def test_deploy_projects_smtp_credentials_and_restarts_app(self):
        module = runpy.run_path(str(ROOT / 'scripts/deploy-helm.py'))
        runtime = {'APP_KEY': 'test-only', 'JWT_SECRET': 'test-only',
                   'POSTGRES_PASSWORD': 'test-only',
                   'DATABASE_URL': 'postgresql://hievents:test-only@hievents-postgres:5432/hievents'}
        env = {'LINODE_KUBECONFIG': base64.b64encode(b'apiVersion: v1\nkind: Config\n').decode(),
               'GHCR_TOKEN': 'test-token', 'HIEVENTS_RUNTIME_JSON': json.dumps(runtime),
               'IMAGE_DIGEST': DIGEST, 'SMTP2GO_USERNAME': 'test-smtp-user',
               'SMTP2GO_PASSWORD': 'test-smtp-password'}
        calls = []
        paths = []

        def run(args, **kwargs):
            calls.append((args, kwargs))
            config = Path(kwargs['env']['KUBECONFIG'])
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            paths.append(config)
            return subprocess.CompletedProcess(args, 0, stdout='namespace/hievents', stderr='')

        with patch.dict(os.environ, env, clear=True), patch('subprocess.run', side_effect=run):
            module['main']()
        payloads = [json.loads(kwargs['input']) for _, kwargs in calls if kwargs.get('input')]
        mail = next(item for item in payloads if item['metadata']['name'] == 'hievents-mail')
        self.assertEqual({k: base64.b64decode(v).decode() for k, v in mail['data'].items()},
                         {'MAIL_USERNAME': env['SMTP2GO_USERNAME'], 'MAIL_PASSWORD': env['SMTP2GO_PASSWORD']})
        for args, _ in calls:
            self.assertNotIn(env['SMTP2GO_PASSWORD'], ' '.join(args))
        self.assertIn('restart', calls[-2][0])
        self.assertIn('status', calls[-1][0])
        self.assertTrue(all(not path.exists() for path in paths))

        for missing in ('SMTP2GO_USERNAME', 'SMTP2GO_PASSWORD'):
            with self.subTest(missing=missing), patch.dict(os.environ, {**env, missing: ''}, clear=True), \
                    patch('subprocess.run') as command:
                with self.assertRaisesRegex(SystemExit, missing):
                    module['main']()
                command.assert_not_called()


if __name__ == '__main__':
    subprocess.run(['helm', 'lint', str(ROOT / 'helm'), '--set', f'image.digest={DIGEST}'], check=True)
    unittest.main()
