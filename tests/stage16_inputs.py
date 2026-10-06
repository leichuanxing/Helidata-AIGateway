"""Pure input validation; no database, network or production state required."""
import json
import math
from app.core.exceptions import APIError
from app.services.route_vectors import encode_vector
from app.schemas.routing import RouteConfigInput, RouteSamplesInput, parse_samples_csv
from pydantic import ValidationError


def validate_inputs():
    assert RouteConfigInput(virtual_model='AI-Auto', embedding_model='embed', simple_model_group=1, complex_model_group=2).status == 'disabled'
    for mutation in ({'top_k': True}, {'top_k': 51}, {'similarity_threshold': float('nan')}, {'confidence_gap': float('inf')}, {'virtual_model': 'a b'}, {'virtual_model': 'embed'}, {'simple_model_group': 2}):
        try:
            RouteConfigInput.model_validate({**dict(virtual_model='AI-Auto', embedding_model='embed', simple_model_group=1, complex_model_group=2), **mutation})
        except ValidationError:
            pass
        else:
            raise AssertionError('invalid config input accepted')
    parsed = parse_samples_csv('prompt,classification\n"你好，世界\n换行",simple\n推理,complex\n'.encode('utf-8-sig'))
    assert parsed[0].prompt == '你好，世界\n换行' and parsed[1].classification == 'complex'
    for raw in (b'', b'prompt,class\na,simple', b'prompt,classification\na,invalid',
                b'prompt,classification\n a ,simple\na,complex', b'prompt,classification\na,simple,extra',
                b'prompt,classification\n"missing quote,simple', b'prompt,classification\n\xff,simple',
                b'x' * (2*1024*1024+1), b'prompt,classification\n' + b''.join(f'{n},simple\n'.encode() for n in range(501))):
        try:
            parse_samples_csv(raw)
        except APIError as error:
            assert 'missing quote' not in error.detail['message'] and '\xff' not in error.detail['message']
        else:
            raise AssertionError('invalid CSV accepted')
    try:
        RouteSamplesInput(config_id=1, samples=[])
    except ValidationError:
        pass
    else:
        raise AssertionError('empty batch accepted')
    print('PASS: bounded route inputs, strict integers, finite thresholds and UTF-8/BOM quoted CSV with row-only failures')
    for vector in ([], [True], [0, 0], [float('nan')], [float('inf')], ['1'], [1e39], [10**1000], [1e-100], [1] * 4097):
        try:
            encode_vector(vector)
        except APIError as error:
            assert error.detail['code'] == 'ROUTE_INVALID_VECTOR'
        else:
            raise AssertionError('invalid embedding accepted')
    assert encode_vector([1, 0])[1] == 2
    assert all(math.isclose(a, b) for a, b in zip(json.loads(encode_vector([1e38, 1e38])[0]), json.loads(encode_vector([1, 1])[0])))
    print('PASS: strict finite, nonzero, float32-compatible Embedding validation')


if __name__ == '__main__':
    validate_inputs()
