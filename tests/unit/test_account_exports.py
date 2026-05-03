import csv
import io

from autoteam.account_exports import export_inventory_csv


def _read_rows(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text.removeprefix("\ufeff"))))


def test_export_inventory_csv_basic():
    csv_text = export_inventory_csv(
        [
            {
                "category": "inventory",
                "email": "inventory@example.com",
                "password": "secret",
                "plan_type": "team",
                "registered_at": 1710000000,
                "updated_at": 1710000100,
                "note": "ready",
            },
            {
                "category": "registered",
                "email": "skip@example.com",
                "password": "hidden",
            },
        ]
    )

    rows = _read_rows(csv_text)

    assert csv_text.startswith("\ufeff")
    assert rows == [
        [
            "email",
            "password",
            "cpa_json_path",
            "auth_file_path",
            "plan_type",
            "registered_at",
            "updated_at",
            "note",
        ],
        [
            "inventory@example.com",
            "secret",
            "",
            "",
            "team",
            "1710000000",
            "1710000100",
            "ready",
        ],
    ]


def test_export_inventory_csv_excludes_main_account():
    csv_text = export_inventory_csv(
        [
            {
                "category": "inventory",
                "email": "main@example.com",
                "is_main_account": True,
            }
        ]
    )

    assert _read_rows(csv_text) == [
        [
            "email",
            "password",
            "cpa_json_path",
            "auth_file_path",
            "plan_type",
            "registered_at",
            "updated_at",
            "note",
        ]
    ]


def test_export_inventory_csv_handles_v2_credentials():
    csv_text = export_inventory_csv(
        [
            {
                "category": "inventory",
                "email": "v2@example.com",
                "credentials": {
                    "oauth_rt": {"path": "auths/v2-oauth.json"},
                    "cpa_archive": {"path": "archives/v2-cpa.json"},
                },
            }
        ]
    )

    rows = _read_rows(csv_text)

    assert rows[1][2] == "archives/v2-cpa.json"
    assert rows[1][3] == "auths/v2-oauth.json"


def test_export_inventory_csv_handles_legacy_flat_fields():
    csv_text = export_inventory_csv(
        [
            {
                "category": "inventory",
                "email": "legacy@example.com",
                "rt_auth_file": "auths/legacy-oauth.json",
                "cpa_json": "archives/legacy-cpa.json",
            }
        ]
    )

    rows = _read_rows(csv_text)

    assert rows[1][2] == "archives/legacy-cpa.json"
    assert rows[1][3] == "auths/legacy-oauth.json"


def test_export_inventory_csv_escapes_commas_in_note():
    csv_text = export_inventory_csv(
        [
            {
                "category": "inventory",
                "email": "comma@example.com",
                "note": "changed,password,keep",
            }
        ]
    )

    lines = csv_text.removeprefix("\ufeff").splitlines()

    assert lines[1].endswith('"changed,password,keep"')
    assert _read_rows(csv_text)[1][7] == "changed,password,keep"


def test_export_inventory_csv_empty_input():
    csv_text = export_inventory_csv([])

    assert _read_rows(csv_text) == [
        [
            "email",
            "password",
            "cpa_json_path",
            "auth_file_path",
            "plan_type",
            "registered_at",
            "updated_at",
            "note",
        ]
    ]
