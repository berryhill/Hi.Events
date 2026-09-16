import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


REQUIRED = ('LINODE_KUBECONFIG', 'GHCR_TOKEN', 'HIEVENTS_RUNTIME_JSON', 'IMAGE_DIGEST')


def main():
    missing = [key for key in REQUIRED if not os.environ.get(key)]
    if missing:
        raise SystemExit('Missing deployment secrets/settings: ' + ', '.join(missing))
    digest = os.environ['IMAGE_DIGEST']
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise SystemExit('Invalid image digest')
    try:
        runtime = json.loads(os.environ['HIEVENTS_RUNTIME_JSON'])
        assert isinstance(runtime, dict)
        assert set(runtime) == {'APP_KEY', 'JWT_SECRET', 'DATABASE_URL', 'POSTGRES_PASSWORD'}
        assert all(isinstance(v, str) and v for v in runtime.values())
        assert runtime['DATABASE_URL'] == ('postgresql://hievents:' + runtime['POSTGRES_PASSWORD'] + '@hievents-postgres:5432/hievents')
    except (ValueError, AssertionError, TypeError):
        raise SystemExit('Invalid runtime secret schema or database wiring') from None
    with tempfile.TemporaryDirectory(prefix='hievents-deploy-') as directory:
        kubeconfig = Path(directory) / 'config'
        kubeconfig.touch(mode=0o600)
        kubeconfig.write_text(os.environ['LINODE_KUBECONFIG'])
        env = {**os.environ, 'KUBECONFIG': str(kubeconfig)}
        kube = ['kubectl', '--context', 'lke428841-ctx']

        def run(args, payload=None):
            result = subprocess.run(args, input=payload, text=True, capture_output=True, env=env)
            if result.returncode:
                raise SystemExit('Deployment command failed: ' + args[0] + '; inspect namespaced workload status. Sensitive output suppressed.')
            return result.stdout

        run(kube + ['get', 'namespace', 'kube-system', '-o', 'name'])
        namespace = run(kube + ['get', 'namespace', 'hievents', '--ignore-not-found', '-o', 'name'])
        if not namespace.strip():
            run(kube + ['create', 'namespace', 'hievents'])
        for name, kind, data in [
            ('hievents-runtime', 'Opaque', runtime),
            ('ghcr-pull', 'kubernetes.io/dockerconfigjson', {'.dockerconfigjson': json.dumps({
                'auths': {'ghcr.io': {'auth': base64.b64encode(('berryhill:' + os.environ['GHCR_TOKEN']).encode()).decode()}}
            })}),
        ]:
            payload = json.dumps({'apiVersion': 'v1', 'kind': 'Secret',
                                  'metadata': {'name': name, 'namespace': 'hievents'},
                                  'type': kind, 'data': {k: base64.b64encode(v.encode()).decode() for k, v in data.items()}})
            run(kube + ['apply', '--server-side', '--field-manager=hievents-deploy', '-f', '-'], payload)
        subprocess.run(['helm', 'upgrade', '--install', 'hievents', './helm',
                        '--kube-context', 'lke428841-ctx', '--namespace', 'hievents',
                        '--reset-values', '--set-string', 'image.digest=' + digest,
                        '--wait', '--timeout', '20m'], env=env, check=True)
        print('Helm rollout passed. DNS, TLS, email, and complete user journeys require separate verification.')


if __name__ == '__main__':
    main()
