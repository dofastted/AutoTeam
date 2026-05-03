import csv
import io

from autoteam.account_exports import dry_run_import_csv, export_inventory_csv, export_sold_csv


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


def test_dry_run_import_csv_basic_add():
    report = dry_run_import_csv(
        "Email,Password\nalice@example.com,pw-a\nbob@example.com,pw-b\n",
        [],
    )

    assert report["headers"] == ["email", "password"]
    assert report["row_count"] == 2
    assert report["to_add"] == [
        {"email": "alice@example.com", "password": "pw-a"},
        {"email": "bob@example.com", "password": "pw-b"},
    ]
    assert report["summary"]["to_add_count"] == 2


def test_dry_run_import_csv_detects_existing_conflict():
    report = dry_run_import_csv(
        "email,password\nused@example.com,pw-used\nnew@example.com,pw-new\n",
        [{"email": "used@example.com"}],
    )

    assert report["to_add"] == [{"email": "new@example.com", "password": "pw-new"}]
    assert report["conflicts"] == [
        {"row_index": 1, "email": "used@example.com", "reason": "duplicate_email"}
    ]
    assert report["summary"]["conflict_count"] == 1


def test_dry_run_import_csv_case_insensitive_email_match():
    report = dry_run_import_csv(
        "email,password\nalice@x.com,pw\n",
        [{"email": "Alice@x.com"}],
    )

    assert report["to_add"] == []
    assert report["conflicts"] == [{"row_index": 1, "email": "alice@x.com", "reason": "duplicate_email"}]


def test_dry_run_import_csv_detects_duplicate_in_csv():
    report = dry_run_import_csv(
        "email,password\nsame@example.com,pw-1\nsame@example.com,pw-2\n",
        [],
    )

    assert report["to_add"] == [{"email": "same@example.com", "password": "pw-1"}]
    assert report["conflicts"] == [{"row_index": 2, "email": "same@example.com", "reason": "duplicate_in_csv"}]


def test_dry_run_import_csv_missing_email_column():
    report = dry_run_import_csv(
        "email,password\n,pw-empty\n",
        [],
    )

    assert report["to_add"] == []
    assert report["missing_fields"] == [{"row_index": 1, "missing": ["email"]}]
    assert report["summary"]["missing_field_count"] == 1


def test_dry_run_import_csv_handles_extra_columns():
    report = dry_run_import_csv(
        "EMAIL,password,cpa_json,remark\nextra@example.com,pw-extra,/tmp/a.json,keep\n",
        [],
    )

    assert report["headers"] == ["email", "password", "cpa_json", "remark"]
    assert report["to_add"] == [
        {
            "email": "extra@example.com",
            "password": "pw-extra",
            "cpa_json": "/tmp/a.json",
            "remark": "keep",
        }
    ]


def test_dry_run_import_csv_empty_input():
    report = dry_run_import_csv("", [])

    assert report == {
        "headers": [],
        "row_count": 0,
        "to_add": [],
        "conflicts": [],
        "missing_fields": [],
        "invalid_rows": [],
        "summary": {
            "total_rows": 0,
            "to_add_count": 0,
            "conflict_count": 0,
            "missing_field_count": 0,
            "invalid_row_count": 0,
        },
    }


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
