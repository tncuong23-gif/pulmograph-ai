import pytest
from scripts.benchmark_stt import error_rates


def test_normalization_preserves_negation_and_numbers():
    assert error_rates(' KHÔNG sốt, SpO2 92.5% ', 'không sốt, spo2 92.5%')['character_error_rate'] == 0
    result = error_rates('không sốt 92.5%', 'sốt 95%')
    assert result['character_error_rate'] > 0
    assert result['whitespace_token_error_rate'] == 2/3


def test_empty_hypothesis_and_reference():
    assert error_rates('không sốt', '')['character_error_rate'] == 1
    with pytest.raises(ValueError): error_rates(' ', 'có sốt')
