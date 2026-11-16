from actions.proactive import is_proactive_mode_enabled


def test_proactive_mode_is_disabled_by_default():
    assert not is_proactive_mode_enabled({})


def test_proactive_mode_accepts_explicit_boolean_values():
    assert is_proactive_mode_enabled({"proactive_mode_enabled": True})
    assert not is_proactive_mode_enabled({"proactive_mode_enabled": False})


def test_proactive_mode_accepts_explicit_string_values():
    assert is_proactive_mode_enabled({"proactive_mode_enabled": "true"})
    assert is_proactive_mode_enabled({"proactive_mode_enabled": "on"})
    assert not is_proactive_mode_enabled({"proactive_mode_enabled": "false"})
    assert not is_proactive_mode_enabled({"proactive_mode_enabled": "off"})
