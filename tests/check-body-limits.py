"""Large compressed histories pass; wire and decoded bodies remain bounded."""
import gzip
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/gateway'))
import core

body = b'x' * (33 * 1024 * 1024)
assert core.decode_body(gzip.compress(body), 'gzip') == body
assert core.decode_body(body, None) == body
assert core.MAX_BODY == 128 * 1024 * 1024

# Exercise the same boundary logic without allocating multiple 128 MiB buffers.
original_limit = core.MAX_BODY
try:
    core.MAX_BODY = 1024
    for encoding in (None, 'identity', 'gzip'):
        for size in (1024, 1025):
            raw = b'x' * size
            wire = gzip.compress(raw) if encoding == 'gzip' else raw
            try:
                decoded = core.decode_body(wire, encoding)
            except core.GatewayError as error:
                assert size == 1025 and error.status == 413
            else:
                assert size == 1024 and decoded == raw
finally:
    core.MAX_BODY = original_limit

print('Body limit checks passed')
