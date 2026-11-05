"""Numeric and string codes of the ETSI MEC data models EdgeGuard exchanges (checked against the ETSI Forge
OpenAPI definitions by tools/mec_conformance.py).

The ETSI definitions encode several enumerations as integers (MEC 012 AssociateId.type and Trigger, MEC 021
mobilityStatus) and MEC 013 distance criteria in camel case.  EdgeGuard sends the ETSI form and reads either
form, so older peers that send names keep working.
"""
from __future__ import annotations

ASSOCIATE_TYPE = {"UE_IPv4_ADDRESS": 1, "UE_IPV6_ADDRESS": 2, "NATED_IP_ADDRESS": 3, "GTP_TEID": 4}
RNIS_TRIGGER = {"NOT_AVAILABLE": 0, "PERIODICAL_REPORT_STRONGEST_CELLS": 1, "PERIODICAL_REPORT_STRONGEST_CELLS_FOR_SON": 2,
                "PERIODICAL_REPORT_CGI": 3, "INTRA_PERIODICAL_REPORT_STRONGEST_CELLS": 4, "INTRA_PERIODICAL_REPORT_CGI": 5,
                "EVENT_A1": 10, "EVENT_A2": 11, "EVENT_A3": 12, "EVENT_A4": 13, "EVENT_A5": 14, "EVENT_A6": 15}
MOBILITY_STATUS = {"INTERHOST_MOVEOUT_TRIGGERED": 1, "INTERHOST_MOVEOUT_COMPLETED": 2, "INTERHOST_MOVEOUT_FAILED": 3}
DISTANCE_CRITERIA = {"ALL_WITHIN_DISTANCE": "AllWithinDistance", "ANY_WITHIN_DISTANCE": "AnyWithinDistance",
                     "ALL_BEYOND_DISTANCE": "AllBeyondDistance", "ANY_BEYOND_DISTANCE": "AnyBeyondDistance"}


def code(table: dict, value):
    """The ETSI integer for a name (an integer passes through)."""
    return table.get(value, value) if isinstance(value, str) else value


def name(table: dict, value):
    """The name for an ETSI integer (a name passes through)."""
    if isinstance(value, str):
        return value
    return next((k for k, v in table.items() if v == value), value)


def distance(value):
    """MEC 013 distance criteria / event in the ETSI camel case."""
    return DISTANCE_CRITERIA.get(value, value)


def ue_id(address: str) -> dict:
    """MEC 012 AssociateId of a UE."""
    return {"type": ASSOCIATE_TYPE["UE_IPv4_ADDRESS"], "value": address}
