"""EXTERNAL EVIDENCE AUDIT - the TASK-409 finding, against the lab artefact it was found in.

Moved out of `test_reset_ab.py` by HYDRA-CI-01. The claim is about ONE artefact
(`experiments/_sweep_cache_etf/audit_steps.pkl`): that the published 50/50 mix already had its
stock sleeve earning the T-bill, so SPEC 9.5's original sentence blamed a confound that was not
there. That is a statement about specific recorded bytes, and a synthetic fixture cannot make it -
it would only restate `sleeve_lab.mix`, which is not the finding.

Everything in `test_reset_ab.py` that IS a property of the code - the paired bootstrap actually
pairing, the verdict rule, the block sampler, the risk-free leg - stays in the required suite and
needs no cache.

Run by `tools/external_audit.py`. No `pytest.skip` in this file.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sleeve_lab as S  # noqa: E402
from reset_ab import AUDIT_STEPS, load_lab  # noqa: E402


def test_the_published_mix_already_had_cash_at_the_t_bill():
    """`P_5050` is `mix(T20_cy + ETF)` to machine precision - the lab's stock sleeve DID earn it.

    The second assertion is the one that makes the first mean something: the mix WITHOUT the
    T-bill leg is measurably different, so the equality above is a fact about this artefact and
    not an identity that would hold whatever was in the file.
    """
    assert os.path.exists(AUDIT_STEPS), AUDIT_STEPS
    lab = load_lab()
    for key in ("P_5050", "T20_cy", "ETF", "T20"):
        assert key in lab, f"{AUDIT_STEPS} has no {key!r}; it is not the artefact this pins"
    p5050 = lab["P_5050"]["net"]
    with_tbill = S.mix([lab["T20_cy"], lab["ETF"]], "equal")["net"]
    without = S.mix([lab["T20"], lab["ETF"]], "equal")["net"]
    assert float((with_tbill - p5050).abs().max()) == 0.0
    assert float((without - p5050).abs().max()) > 1e-6
