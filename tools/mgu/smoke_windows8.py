"""Cold-boot the Windows MGU22 runtime and retain logs and frames."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from idemu import mgu


def run(output, timeout):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    rt = mgu.MguRuntime(str(output), {'id': 'mgu8-port-smoke', 'kind': 'mgu22', 'coding': {}})
    started = time.monotonic(); previous = None
    try:
        rt.start(cold=True)
        while time.monotonic() - started < timeout:
            status = rt.status()
            current = (status['state'], status['boot_step'], status['frame_seq'], status['error'])
            if current != previous:
                print(json.dumps(status, ensure_ascii=True), flush=True); previous = current
            if status['state'] == 'error': raise RuntimeError(status['error'])
            if status['state'] == 'running':
                # Early EGL swaps can still be black; wait for actual HMI content.
                deadline = time.monotonic() + 60
                while True:
                    frame = rt.frame_bytes()
                    if frame and len(set(frame[3][::1024])) > 8: break
                    if time.monotonic() > deadline: raise TimeoutError('Guest swaps remained blank')
                    time.sleep(.5)
                time.sleep(10)  # Let the first-screen transition finish before comparing input.
                def capture(filename):
                    png, _ = rt.screen_png()
                    if png: (output / filename).write_bytes(png)
                capture('first-frame.png')
                rt.rotor(1); time.sleep(3); capture('after-rotor.png')
                rt.key(8, 1); time.sleep(.15); rt.key(8, 0)
                time.sleep(3); capture('after-input.png')
                rt.touch(1584, 900, True); rt.touch(1584, 900, False)
                time.sleep(3); capture('after-touch.png')
                rt.key(2, 1); time.sleep(.15); rt.key(2, 0)
                time.sleep(3); capture('after-back.png')
                (output / 'summary.json').write_text(json.dumps(rt.status(), indent=2), encoding='utf-8')
                print('PASS: native guest produced frames; input sent (inspect retained frames to confirm response)', flush=True)
                return
            time.sleep(5)
        raise TimeoutError('No HMI frame within smoke-test timeout; logs retained at ' + str(output))
    finally:
        rt.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'scratch/mgu8-boot-smoke'))
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    run(args.output, args.timeout)
