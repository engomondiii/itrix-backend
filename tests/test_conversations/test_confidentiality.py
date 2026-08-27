from apps.conversations.services import confidentiality


def test_prospective_nonconfidential_boundary_is_not_treated_as_disclosure():
    text = (
        "Before I share confidential details, please evaluate our inference workload. "
        "What information do you need first?"
    )
    assert confidentiality.detect(text).sensitive is False


def test_actual_unreleased_identifier_still_intercepts():
    text = "Our confidential prototype is ZETA-847 and here are the internal details."
    hit = confidentiality.detect(text)
    assert hit.sensitive is True
    assert hit.reason == "unreleased_specification"


def test_actual_unreleased_numeric_spec_still_intercepts():
    text = "Our unreleased accelerator runs at 4.2 TFLOPs and 31W."
    hit = confidentiality.detect(text)
    assert hit.sensitive is True
    assert hit.reason == "unreleased_specification"
