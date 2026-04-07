import logging

from waapi import WaapiClient

CUSTOM_ATTENUATION_WAQL = '$ from type Attenuation where owner != null'
DEFAULT_ATTENUATION_WORK_UNIT_PATH = r"\Attenuations\Default Work Unit"
DEFAULT_SHARESET_NAME = "ATT_AUTO_"

CURVE_TYPES = [
    "VolumeDryUsage",
    "VolumeWetGameUsage",
    "VolumeWetUserUsage",
    "LowPassFilterUsage",
    "HighPassFilterUsage",
    "SpreadUsage",
    "FocusUsage",
    "ObstructionVolumeUsage",
    "ObstructionHPFUsage",
    "ObstructionLPFUsage",
    "OcclusionVolumeUsage",
    "OcclusionHPFUsage",
    "OcclusionLPFUsage",
    "DiffractionVolumeUsage",
    "DiffractionHPFUsage",
    "DiffractionLPFUsage",
    "TransmissionVolumeUsage",
    "TransmissionHPFUsage",
    "TransmissionLPFUsage",
]


def waql_get(client, waql_query, fields_to_return):
    """Fetch objects with WAQL and return the "return" list safely."""
    response = client.call(
        "ak.wwise.core.object.get",
        {"waql": waql_query},
        options={"return": fields_to_return},
    )
    return response.get("return", [])


def resolve_attenuation_parent_id(client):
    """Resolve the default attenuation work unit ID."""
    by_path = client.call(
        "ak.wwise.core.object.get",
        {"from": {"path": [DEFAULT_ATTENUATION_WORK_UNIT_PATH]}},
        options={"return": ["id"]},
    )
    parent = by_path.get("return", [])
    if not parent:
        raise RuntimeError(f"Could not find attenuation work unit: {DEFAULT_ATTENUATION_WORK_UNIT_PATH}")
    return parent[0]["id"]


def create_shareset(client, parent_id, owner_name):
    """Create a new attenuation shareset for a given owner name."""
    default_name = f"{DEFAULT_SHARESET_NAME}{owner_name}"
    created_shareset = client.call(
        "ak.wwise.core.object.create",
        {
            "parent": parent_id,
            "type": "Attenuation",
            "name": default_name,
            "onNameConflict": "rename",
        },
    )
    shareset_id = created_shareset.get("id")
    if not shareset_id:
        raise RuntimeError(f"Created attenuation '{default_name}', but no ID was returned.")
    return shareset_id, created_shareset.get("name", default_name)


def copy_curves(client, source_att_id, target_att_id):
    """Copy all supported attenuation curves from source to target."""
    for curve_type in CURVE_TYPES:
        try:
            source_curve = client.call(
                "ak.wwise.core.object.getAttenuationCurve",
                {"object": source_att_id, "curveType": curve_type},
            )

            use_value = source_curve.get("use", "None")

            points = source_curve.get("points", []) if use_value == "Custom" else []

            client.call(
                "ak.wwise.core.object.setAttenuationCurve",
                {
                    "object": target_att_id,
                    "curveType": curve_type,
                    "use": use_value,
                    "points": points,
                },
            )
        except Exception as exc:
            logging.warning("Failed curve copy for %s: %s", curve_type, exc)


def assign_shareset_to_owner(client, owner_id, shareset_id):
    """Assign the created attenuation shareset to the owner object."""
    try:
        client.call(
            "ak.wwise.core.object.setReference",
            {"object": owner_id, "reference": "Attenuation", "value": shareset_id},
        )
    except Exception as exc:
        logging.warning("Failed assigning shareset to owner %s: %s", owner_id, exc)


def main():
    """Orchestrate shareset creation, copy, assignment, and summary logs."""
    created = []
    success = 0
    failed = 0

    try:
        with WaapiClient() as client:
            parent_id = resolve_attenuation_parent_id(client)
            custom_atts = waql_get(client, CUSTOM_ATTENUATION_WAQL, ["id"])

            for custom_att in custom_atts:
                source_id = custom_att["id"]
                owner_data = waql_get(
                    client,
                    f'$ "{source_id}" select owner',
                    ["id", "name"],
                )
                if not owner_data:
                    failed += 1
                    continue
                owner = owner_data[0]

                try:
                    shareset_id, shareset_name = create_shareset(
                        client,
                        parent_id,
                        owner["name"],
                    )
                    radius_max = waql_get(client, f'$ "{source_id}"', ["@RadiusMax"])[0]["@RadiusMax"]
                    client.call(
                        "ak.wwise.core.object.setProperty",
                        {"object": shareset_id, "property": "RadiusMax", "value": radius_max},
                    )
                    copy_curves(client, source_id, shareset_id)
                    assign_shareset_to_owner(client, owner["id"], shareset_id)
                    created.append(shareset_name)
                    success += 1
                except Exception as exc:
                    logging.warning("Failed processing source %s: %s", source_id, exc)
                    failed += 1
    except Exception as exc:
        logging.exception("Script failed: %s", exc)
        return

    for shareset_name in created:
        logging.info("created: %s", shareset_name)
    logging.info("success: %s", success)
    logging.info("failed: %s", failed)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
