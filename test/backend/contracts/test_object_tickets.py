# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest
from contracts.object_tickets import (
    InvalidObjectTicket,
    issue_object_ticket,
    open_object_ticket,
)


def test_round_trip_preserves_exact_key_until_expiry():
    key = r"attachments/owner/文件:a\b.txt"
    ticket = issue_object_ticket(key, 60, secret="synthetic", now=100)
    assert open_object_ticket(ticket, secret="synthetic", now=159) == key
    with pytest.raises(InvalidObjectTicket):
        open_object_ticket(ticket, secret="synthetic", now=160)


def test_tampering_and_key_rotation_reject_the_ticket():
    ticket = issue_object_ticket("attachments/owner/a.txt", 60, secret="synthetic", now=100)
    prefix, claims, signature = ticket.split(".")
    for invalid in (f"{prefix}.{claims}A.{signature}", ticket + "A", "wrong." + claims + "." + signature):
        with pytest.raises(InvalidObjectTicket):
            open_object_ticket(invalid, secret="synthetic", now=100)
    with pytest.raises(InvalidObjectTicket):
        open_object_ticket(ticket, secret="different", now=100)


@pytest.mark.parametrize("key, ttl", [("", 5), ("a\x00b", 5), ("x" * 1025, 5), ("a", 0), ("a", 604801)])
def test_invalid_tickets_are_never_issued(key, ttl):
    with pytest.raises(InvalidObjectTicket):
        issue_object_ticket(key, ttl, secret="synthetic", now=100)
