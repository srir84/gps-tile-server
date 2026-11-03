"""tests/data/check_gbif.py's download.json rule (step 18): only a finished simple-CSV download of exactly
HAS_COORDINATE = true AND YEAR = 2024 is the dataset DESIGN §13 describes. No data needed: the rule is a function."""
import copy
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("check_gbif", pathlib.Path(__file__).resolve().parents[1] / "data" / "check_gbif.py")
check_gbif = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_gbif)

GBIF_SHAPE = {"status": "SUCCEEDED", "request": {"format": "SIMPLE_CSV", "type": "OCCURRENCE", "predicate": {
    "type": "and", "predicates": [
        {"type": "equals", "key": "HAS_COORDINATE", "value": "true", "matchCase": False},
        {"type": "equals", "key": "YEAR", "value": "2024", "matchCase": False}]}}}


def changed(edit):
    info = copy.deepcopy(GBIF_SHAPE)
    edit(info)
    return info


def test_only_the_exact_2024_query_is_the_known_download():
    """catches: the query check flattened to key=value pairs again, so an "or", a ">=" on the year, a third condition, another format or an unfinished download passes as DESIGN §13's (Codex, step 18)"""
    query = lambda info: info["request"]["predicate"]
    assert check_gbif.is_the_2024_download(GBIF_SHAPE)
    assert check_gbif.is_the_2024_download(changed(lambda i: query(i)["predicates"].reverse()))
    refused = {
        "or": lambda i: query(i).update(type="or"),
        ">=": lambda i: query(i)["predicates"][1].update(type="greaterThanOrEquals"),
        "a third condition": lambda i: query(i)["predicates"].append({"type": "equals", "key": "COUNTRY", "value": "NL"}),
        "YEAR twice": lambda i: query(i)["predicates"].__setitem__(0, {"type": "equals", "key": "YEAR", "value": "2024"}),
        "another year": lambda i: query(i)["predicates"][1].update(value="2023"),
        "without coordinates": lambda i: query(i)["predicates"][0].update(value="false"),
        "Darwin Core Archive": lambda i: i["request"].update(format="DWCA"),
        "not finished": lambda i: i.update(status="RUNNING"),
        "no query": lambda i: i["request"].pop("predicate"),
    }
    for name, edit in refused.items():
        assert not check_gbif.is_the_2024_download(changed(edit)), name
