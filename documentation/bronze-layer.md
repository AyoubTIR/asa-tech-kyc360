# Bronze Layer — Customer Feedback Ingestion

## 1. Overview
The Bronze layer provides an **append-only, immutable raw landing zone** in Databricks Free Edition (Unity Catalog + Delta Lake) for customer campaign feedback batches. Each pipeline execution preserves the original raw JSON payload in a Unity Catalog Volume and appends the parsed records—along with batch lineage metadata—into the Bronze Delta table.

---

## 2. Infrastructure as Code (Databricks Asset Bundles)
All Bronze resources are defined declaratively using **Databricks Asset Bundles** and deployed with a single CLI command (`databricks bundle deploy`):

- **Bundle Entry Point:** [databricks.yml](../databricks.yml)
- **Resource Definitions:** [infra/bronze_feedback.yml](../infra/bronze_feedback.yml)

| Resource Type | Identifier | Description |
| --- | --- | --- |
| Unity Catalog Schema | `workspace.bronze` | Bronze layer schema in the Free Edition default catalog (`workspace`) |
| Managed Volume | `/Volumes/workspace/bronze/raw_feedback` | Raw JSON landing zone storing replayable batch files |
| Lakeflow Job | `kyc360-bronze-feedback-ingestion` | Serverless job running [scripts/bronze_feedback_ingest.py](../scripts/bronze_feedback_ingest.py) |
| Delta Table | `workspace.bronze.raw_customer_feedback` | Append-only Bronze table created and populated by the PySpark job |

### Configurable Bundle Variables (`databricks.yml`)
- `catalog_name` (default: `workspace`)
- `schema_name` (default: `bronze`)
- `volume_name` (default: `raw_feedback`)
- `table_name` (default: `raw_customer_feedback`)
- `batch_size` (default: `"50"`)

---

## 3. Pipeline Design & Implementation
The ingestion notebook/script [scripts/bronze_feedback_ingest.py](../scripts/bronze_feedback_ingest.py) executes three steps on Databricks Serverless compute:

1. **Generate Feedback JSON Batch (`api_pusher` — `manual` mode):**
   - Imports `generate_random_feedback` from [scripts/api_pusher/src/business/generate_campaign_feedback.py](../scripts/api_pusher/src/business/generate_campaign_feedback.py).
   - Generates `batch_size` feedback records (`username`, `feedback_date`, `campaign_id`, and multilingual `comment` across EN, FR, HI, ZH, and JA).
2. **Land Raw JSON in Unity Catalog Volume:**
   - Generates a unique `batch_id` (`uuid.uuid4().hex`) and UTC timestamp (`ingested_at`).
   - Writes the JSON array to `/Volumes/workspace/bronze/raw_feedback/feedback_<batch_id>.json` so original raw batches remain preserved and replayable.
3. **Append to Bronze Delta Table (PySpark):**
   - Ensures `workspace.bronze.raw_customer_feedback` exists (`CREATE TABLE IF NOT EXISTS ... USING DELTA`).
   - Reads the landed multiline JSON file using an explicit Spark `StructType` schema (`username`, `feedback_date`, `campaign_id`, `comment`).
   - Enriches each record with `batch_id`, `ingested_at`, and `source_file`, then writes via `.write.mode("append").saveAsTable(...)`.
   - Because Bronze is **append-only**, running the job multiple times adds new raw batches without overwriting historical records; deduplication and Delta upserts (`MERGE INTO`) are handled downstream in the Silver layer.

---

## 4. Table Schema (`workspace.bronze.raw_customer_feedback`)

| Column | Type | Description |
| --- | --- | --- |
| `username` | `STRING` | Generated customer identifier (e.g., `user_4629`) |
| `feedback_date` | `STRING` | Feedback date in `YYYY-MM-DD` format |
| `campaign_id` | `STRING` | Marketing campaign identifier (e.g., `CAMP103`) |
| `comment` | `STRING` | Raw customer evaluation text (EN / FR / HI / ZH / JA) |
| `batch_id` | `STRING` | Unique UUID hex identifier for the ingestion batch |
| `ingested_at` | `TIMESTAMP` | UTC timestamp when the batch was ingested |
| `source_file` | `STRING` | Unity Catalog Volume path of the raw JSON batch file |

---

## 5. How to Deploy & Run

### Option A: Databricks Web Terminal (Recommended on Free Edition)
Open a notebook attached to **Serverless** compute and click the **Terminal** (`>_`) icon:

```bash
# Clone the repo (or navigate to your Databricks Git folder)
git clone https://github.com/AyoubTIR/asa-tech-kyc360.git
cd asa-tech-kyc360

# Validate and deploy schema, volume, and Lakeflow job
databricks bundle validate
databricks bundle deploy

# Trigger a run (or use "Run now" in Lakeflow Jobs UI)
databricks bundle run bronze_feedback_ingestion
```

### Option B: Local CLI
```bash
databricks auth login --host https://<your-workspace-url>
databricks bundle deploy
databricks bundle run bronze_feedback_ingestion
```

### Adjusting Batch Size
In the Databricks **Lakeflow Jobs** UI, click **Run now with different parameters** on `kyc360-bronze-feedback-ingestion` and override `batch_size` (default `50`), or update `batch_size` in [databricks.yml](../databricks.yml) and re-run `databricks bundle deploy`.

---

## 6. Verification & Observed Sample Output

### Databricks SQL Verification Queries
```sql
SELECT *
FROM workspace.bronze.raw_customer_feedback
ORDER BY ingested_at DESC
LIMIT 100;
```

```sql
SELECT batch_id, ingested_at, COUNT(*) AS row_count
FROM workspace.bronze.raw_customer_feedback
GROUP BY batch_id, ingested_at
ORDER BY ingested_at DESC;
```

### Sample Verified Run (`batch_id = 95650256bd494f7daf849c6cea018715`, 50 rows)

| username | feedback_date | campaign_id | comment | batch_id | ingested_at | source_file |
| --- | --- | --- | --- | --- | --- | --- |
| `user_4629` | `2024-06-27` | `CAMP103` | `Excellente campagne !` | `95650256bd494f7daf849c6cea018715` | `2026-11-25T08:12:41.764+00:00` | `/Volumes/workspace/bronze/raw_feedback/feedback_95650256bd494f7daf849c6cea018715.json` |
| `user_2136` | `2024-04-15` | `CAMP871` | `もっと整理できると思います。` | `95650256bd494f7daf849c6cea018715` | `2026-11-25T08:12:41.764+00:00` | `/Volumes/workspace/bronze/raw_feedback/feedback_95650256bd494f7daf849c6cea018715.json` |
| `user_213` | `2024-09-30` | `CAMP785` | `मुझे उत्पाद की प्रस्तुति बहुत पसंद आई।` | `95650256bd494f7daf849c6cea018715` | `2026-11-25T08:12:41.764+00:00` | `/Volumes/workspace/bronze/raw_feedback/feedback_95650256bd494f7daf849c6cea018715.json` |
| `user_1941` | `2026-05-27` | `CAMP845` | `很喜欢产品的展示。` | `95650256bd494f7daf849c6cea018715` | `2026-11-25T08:12:41.764+00:00` | `/Volumes/workspace/bronze/raw_feedback/feedback_95650256bd494f7daf849c6cea018715.json` |
| `user_3181` | `2026-05-25` | `CAMP210` | `Too many details, hard to follow.` | `95650256bd494f7daf849c6cea018715` | `2026-11-25T08:12:41.764+00:00` | `/Volumes/workspace/bronze/raw_feedback/feedback_95650256bd494f7daf849c6cea018715.json` |
