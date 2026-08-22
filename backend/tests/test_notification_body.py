"""Bodies, which used to be one line of backend spelling."""
from datetime import datetime, timedelta

import pytest

from proxploy.services.notification_body import compose, human_duration, job_facts

T0 = datetime(2026, 8, 22, 12, 0, 0)


@pytest.mark.parametrize("seconds,expected", [
    (0, "0s"), (9, "9s"), (59, "59s"), (60, "1m 0s"), (134, "2m 14s"),
    (3599, "59m 59s"), (3600, "1h 0m"), (7830, "2h 10m"),
])
def test_a_duration_reads_like_a_person_wrote_it(seconds, expected):
    assert human_duration(T0, T0 + timedelta(seconds=seconds)) == expected


@pytest.mark.parametrize("started,finished", [
    (None, T0), (T0, None), (None, None),
])
def test_a_job_that_never_started_has_no_duration(started, finished):
    """Empty, not "0s". Never started and took no time are different facts."""
    assert human_duration(started, finished) == ""


def test_a_clock_that_went_backwards_says_nothing_rather_than_a_negative():
    assert human_duration(T0, T0 - timedelta(seconds=5)) == ""


def test_the_body_carries_the_facts_then_the_reason():
    body = compose([("App", "nextcloud"), ("Took", "2m 14s"), ("Job", "#412")],
                   "out of disk")
    assert body == (
        "- **App:** nextcloud\n"
        "- **Took:** 2m 14s\n"
        "- **Job:** #412\n"
        "\n"
        "out of disk"
    )


def test_a_fact_with_no_value_is_dropped_rather_than_printed_empty():
    """"Host: " tells a reader Proxploy does not know, which is never the
    thing worth waking them for."""
    body = compose([("App", "nextcloud"), ("Host", ""), ("Job", "#412")])
    assert "Host" not in body
    assert body == "- **App:** nextcloud\n- **Job:** #412"


def test_the_body_never_repeats_the_title():
    """Every service shows the two separately, and an email whose subject and
    first line are identical reads like a template that got away."""
    body = compose([("App", "nextcloud")], "boom")
    assert "App install failed" not in body


def test_job_facts_names_the_target_by_its_type():
    facts = dict(job_facts(job_id=412, target_name="nextcloud", target_type="app",
                           duration="2m 14s", schedule_name=None))
    assert facts["App"] == "nextcloud"
    assert facts["Job"] == "#412"
    assert facts["Ran from"] == ""


def test_job_facts_says_where_an_unattended_run_came_from():
    """The first question about anything arriving at 4am is whether a person
    did it."""
    facts = dict(job_facts(job_id=9, target_name="pve1", target_type="host",
                           duration="1m 0s", schedule_name="Nightly backup"))
    assert facts["Ran from"] == "Nightly backup"
    assert facts["Host"] == "pve1"


def test_a_target_type_with_an_underscore_still_reads_as_words():
    facts = dict(job_facts(job_id=1, target_name="tank", target_type="storage_pool",
                           duration="", schedule_name=None))
    assert "Storage pool" in facts
