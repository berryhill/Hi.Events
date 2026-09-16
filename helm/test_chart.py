import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
DIGEST = 'sha256:' + 'a' * 64


def render(*args):
    return subprocess.run(
        ['helm', 'template', 'hievents', str(ROOT / 'helm'), '--namespace', 'hievents', *args],
        capture_output=True, text=True,
    )


class ChartTests(unittest.TestCase):
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
        ingress = next(d for d in docs if d['kind'] == 'Ingress')
        self.assertEqual(ingress['spec']['rules'][0]['host'], 'admin.elementafestival.com')
        self.assertEqual(ingress['spec']['tls'][0]['hosts'], ['admin.elementafestival.com'])
        config = next(d for d in docs if d['kind'] == 'ConfigMap')['data']
        self.assertEqual(config['APP_DISABLE_REGISTRATION'], 'true')
        self.assertEqual(config['VITE_API_URL_CLIENT'], 'https://admin.elementafestival.com/api')
        self.assertEqual(config['QUEUE_CONNECTION'], 'redis')
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


if __name__ == '__main__':
    subprocess.run(['helm', 'lint', str(ROOT / 'helm'), '--set', f'image.digest={DIGEST}'], check=True)
    unittest.main()
