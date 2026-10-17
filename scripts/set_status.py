#!/usr/bin/env python3
import argparse
import datetime as dt
from build_pack import ROOT, BuildError
from pack_state import read_release, write_release, refresh, payload_digest, require_ci_evidence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('status', choices=['CANDIDATE', 'READY_FOR_GPU', 'GPU_RETRY', 'GPU_PASS'])
    ap.add_argument('--folder', default='candidate')
    ap.add_argument('--gpu-payload-sha256')
    args = ap.parse_args()
    folder = ROOT / args.folder
    if args.status == 'GPU_PASS':
        release = require_ci_evidence(folder)
        if args.gpu_payload_sha256 != payload_digest(folder):
            raise BuildError('GPU tested payload differs from candidate')
        release['validation']['gpu_payload_sha256'] = args.gpu_payload_sha256
    else:
        release = read_release(folder)
        release.get('validation', {}).pop('gpu_payload_sha256', None)
    release.update(status=args.status, status_updated_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    write_release(folder, release)
    refresh(folder)
    print(args.status)


if __name__ == '__main__':
    main()
