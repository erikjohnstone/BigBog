from importlib import metadata


def test_bacpypes3_round_trips_protocol_primitives() -> None:
    from bacpypes3.primitivedata import Boolean, ObjectIdentifier, Real

    for value in (ObjectIdentifier("analog-input,1"), Real(42.5), Boolean(True)):
        assert type(value).decode(value.encode()) == value


def test_bac0_lab_dependency_uses_expected_bacpypes_generation() -> None:
    import BAC0

    assert metadata.version("BAC0") == "2026.7.25"
    assert BAC0.version
