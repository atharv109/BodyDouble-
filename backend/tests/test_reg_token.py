"""B3 (real run 5): the registration token rides in user_data to the forensics
ISO, whose metadata validator only accepts SAFE_ID ([A-Za-z0-9-]). A token with
'_' (token_urlsafe: ~40% of draws) made the ISO reject the whole envelope, so
the sealed boot never brought up its VPC interface and never registered."""
from bd_forensics.metadata import SAFE_ID

from backend.service import new_reg_token


def test_reg_tokens_always_pass_the_iso_validator():
    tokens = {new_reg_token() for _ in range(3000)}
    assert len(tokens) == 3000  # still unguessable / unique
    for token in tokens:
        assert SAFE_ID.fullmatch(token), token
        assert token.startswith("twreg-")
        assert len(token) >= 6 + 32  # at least 128 bits after the prefix
