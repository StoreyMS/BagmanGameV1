from datetime import date, datetime, timezone

import pytest

from bagman.db import Database
from bagman.models import Evidence, Settlement


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "t.db")


@pytest.fixture
def acme():
    return Settlement(
        id="tca:acme", title="Acme Widgets $4.5M settlement", url="https://example.com/acme", source="test",
        claim_url=None, deadline=date(2027, 3, 15), class_period_start=date(2019, 1, 1),
        class_period_end=date(2023, 12, 31), proof_required=False, keywords=["Acme Widgets", "Acme"],
    )


def ev(sender, subject, when=(2021, 5, 4), snippet=""):
    return Evidence(source="static", external_id=f"{sender}{subject}", sender=sender, subject=subject,
                    sent_at=datetime(*when, tzinfo=timezone.utc), snippet=snippet)
