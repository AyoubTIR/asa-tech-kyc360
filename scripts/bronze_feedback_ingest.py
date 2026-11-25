# Databricks notebook source
"""Generate a raw customer feedback JSON batch via api_pusher, land it in a Unity Catalog Volume, and append to Bronze Delta."""

# COMMAND ----------

import datetime
import json
import os
import sys
import uuid

# COMMAND ----------


def get_param(name: str, default: str) -> str:
    """Read a Databricks widget parameter, falling back to env/default locally."""
    if "dbutils" in globals():
        try:
            globals()["dbutils"].widgets.text(name, default)
            val = globals()["dbutils"].widgets.get(name)
            if val:
                return val
        except Exception:
            pass
    return os.environ.get(name.upper(), default)


CATALOG_NAME = get_param("catalog_name", "workspace")
SCHEMA_NAME = get_param("schema_name", "bronze")
VOLUME_NAME = get_param("volume_name", "raw_feedback")
TABLE_NAME = get_param("table_name", "raw_customer_feedback")
BATCH_SIZE = int(get_param("batch_size", "50"))
API_PUSHER_SRC = get_param("api_pusher_src", "")

# COMMAND ----------


def resolve_api_pusher_src(configured_path: str) -> str:
    """Locate scripts/api_pusher/src in Databricks Workspace or a local checkout."""
    candidates = []
    if configured_path:
        candidates.append(configured_path)
        if not configured_path.startswith("/Workspace"):
            candidates.append(f"/Workspace{configured_path}")
    candidates.append(os.path.join(os.getcwd(), "api_pusher", "src"))
    if "__file__" in globals():
        candidates.append(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_pusher", "src")
        )

    for path in candidates:
        if path and os.path.isdir(path):
            return path
    raise FileNotFoundError(f"Could not locate api_pusher/src. Checked: {candidates}")


api_src = resolve_api_pusher_src(API_PUSHER_SRC)
if api_src not in sys.path:
    sys.path.insert(0, api_src)

from business.generate_campaign_feedback import generate_random_feedback

# COMMAND ----------


def generate_feedback_batch(batch_size: int) -> tuple[str, str, list[dict]]:
    """Generate a feedback batch using api_pusher's manual generator."""
    batch_id = uuid.uuid4().hex
    ingested_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    records = generate_random_feedback(feedbacks_to_push=batch_size, payload=[])
    return batch_id, ingested_at, records


def land_raw_json(records: list[dict], volume_dir: str, batch_id: str) -> str:
    """Write the raw JSON array batch to the Unity Catalog landing volume."""
    os.makedirs(volume_dir, exist_ok=True)
    file_path = os.path.join(volume_dir, f"feedback_{batch_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return file_path


def ingest_to_bronze(
    spark_session,
    json_path: str,
    full_table_name: str,
    batch_id: str,
    ingested_at: str,
) -> int:
    """Read landed JSON from the volume and append to the Bronze Delta table."""
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType, StructField, StructType

    schema = StructType(
        [
            StructField("username", StringType(), False),
            StructField("feedback_date", StringType(), False),
            StructField("campaign_id", StringType(), False),
            StructField("comment", StringType(), False),
        ]
    )

    spark_session.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {full_table_name} (
            username STRING,
            feedback_date STRING,
            campaign_id STRING,
            comment STRING,
            batch_id STRING,
            ingested_at TIMESTAMP,
            source_file STRING
        )
        USING DELTA
        COMMENT 'Raw customer feedback JSON batches landed from api_pusher'
        """
    )

    df = (
        spark_session.read.option("multiline", "true")
        .schema(schema)
        .json(json_path)
        .withColumn("batch_id", F.lit(batch_id))
        .withColumn("ingested_at", F.to_timestamp(F.lit(ingested_at)))
        .withColumn("source_file", F.lit(json_path))
    )

    row_count = df.count()
    df.write.mode("append").saveAsTable(full_table_name)
    return row_count


# COMMAND ----------


def main() -> None:
    batch_id, ingested_at, records = generate_feedback_batch(BATCH_SIZE)
    volume_dir = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{VOLUME_NAME}"
    full_table_name = f"{CATALOG_NAME}.{SCHEMA_NAME}.{TABLE_NAME}"

    if "spark" in globals():
        json_path = land_raw_json(records, volume_dir, batch_id)
        written = ingest_to_bronze(
            globals()["spark"], json_path, full_table_name, batch_id, ingested_at
        )
        print(f"Landed {len(records)} records at {json_path}")
        print(f"Appended {written} rows to {full_table_name} (batch_id={batch_id})")
    else:
        print(f"[DRY RUN] Generated {len(records)} records (batch_id={batch_id})")
        print(json.dumps(records[:3], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
