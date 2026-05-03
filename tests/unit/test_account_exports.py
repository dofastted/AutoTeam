import csv
import io

from autoteam.account_exports import export_inventory_csv, export_sold_csv


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


def test_export_sold_csv_basic():
    csv_text = export_sold_csv(
        [
            {
                "email": "sold@example.com",
                "usage_status": "sold",
                "sold_at": 1710000200,
                "sold_to": "buyer-a",
                "sale_price": 88,
                "sale_note": "done",
                "sale_batch_id": "batch-1",
                "plan_type": "team",
                "inventory_at": 1709999000,
            },
            {
                "email": "inventory@example.com",
                "usage_status": "inventory",
                "plan_type": "team",
                "inventory_at": 1709998000,
            },
        ]
    )

    rows = _read_rows(csv_text)

    assert csv_text.startswith("\ufeff")
    assert rows == [
        [
            "email",
            "sold_at",
            "sold_to",
            "sale_price",
            "sale_note",
            "sale_batch_id",
            "plan_type",
            "original_inventory_at",
        ],
        [
            "sold@example.com",
            "1710000200",
            "buyer-a",
            "88",
            "done",
            "batch-1",
            "team",
            "1709999000",
        ],
    ]


def test_export_sold_csv_v2_sale_block():
    csv_text = export_sold_csv(
        [
            {
                "email": "v2@example.com",
                "sale": {
                    "sold_at": 1710000300.9,
                    "sold_to": "buyer-v2",
                    "price": 99.5,
                    "note": "v2 note",
                    "batch_id": "sale-batch-v2",
                },
                "plan_type": "plus",
                "allocation": {"allocated_at": 1709999100},
            }
        ]
    )

    assert _read_rows(csv_text) == [
        [
            "email",
            "sold_at",
            "sold_to",
            "sale_price",
            "sale_note",
            "sale_batch_id",
            "plan_type",
            "original_inventory_at",
        ],
        [
            "v2@example.com",
            "1710000300",
            "buyer-v2",
            "99.5",
            "v2 note",
            "sale-batch-v2",
            "plus",
            "1709999100",
        ],
    ]


def test_export_sold_csv_legacy_flat_fields():
    csv_text = export_sold_csv(
        [
            {
                "email": "legacy@example.com",
                "usage_status": "sold",
                "sold_at": 1710000400,
                "sold_to": "legacy-buyer",
                "sale_price": "188",
                "sale_note": "legacy note",
                "sale_batch_id": "legacy-batch",
                "plan_type": "team",
                "allocation": {"allocated_at": 1709999200},
            }
        ]
    )

    assert _read_rows(csv_text) == [
        [
            "email",
            "sold_at",
            "sold_to",
            "sale_price",
            "sale_note",
            "sale_batch_id",
            "plan_type",
            "original_inventory_at",
        ],
        [
            "legacy@example.com",
            "1710000400",
            "legacy-buyer",
            "188",
            "legacy note",
            "legacy-batch",
            "team",
            "1709999200",
        ],
    ]


def test_export_sold_csv_legacy_status_field():
    csv_text = export_sold_csv(
        [
            {
                "email": "old-status@example.com",
                "status": "sold",
                "sold_at": 1710000500,
                "sold_to": "buyer-old",
                "plan_type": "team",
            }
        ]
    )

    assert _read_rows(csv_text) == [
        [
            "email",
            "sold_at",
            "sold_to",
            "sale_price",
            "sale_note",
            "sale_batch_id",
            "plan_type",
            "original_inventory_at",
        ],
        [
            "old-status@example.com",
            "1710000500",
            "buyer-old",
            "",
            "",
            "",
            "team",
            "",
        ],
    ]


def test_export_sold_csv_empty_input():
    csv_text = export_sold_csv([])

    assert _read_rows(csv_text) == [
        [
            "email",
            "sold_at",
            "sold_to",
            "sale_price",
            "sale_note",
            "sale_batch_id",
            "plan_type",
            "original_inventory_at",
        ]
    ]
