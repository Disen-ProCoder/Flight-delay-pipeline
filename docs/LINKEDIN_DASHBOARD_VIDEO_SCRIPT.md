# LinkedIn Dashboard Walkthrough Video Plan

Goal: create a short LinkedIn video that shows how the Flight Delay Analysis Pipeline works through the Apache Airflow dashboard, with a clear voiceover explaining each button, signal, graph, and workflow step.

Recommended length: 2 to 3 minutes.

Recommended format: 1920x1080 horizontal for LinkedIn feed. Export as MP4.

## What This Dashboard Actually Is

This project does not include a custom BI dashboard frontend. The main dashboard is Apache Airflow, available at:

```text
http://localhost:8080
Username: admin
Password: admin
```

Airflow is the operations dashboard for the pipeline. It shows whether the ETL workflow is scheduled, running, successful, failed, skipped, or waiting. The strongest video story is:

1. Show the Airflow DAG list.
2. Open the `flight_delay_pipeline` DAG.
3. Explain the Graph view and task dependencies.
4. Trigger a manual run.
5. Open task logs and explain what each step is doing.
6. Show green success states.
7. Show the analytics SQL views/queries that the loaded data can power.

## Before Recording

Start the dashboard:

```powershell
docker-compose up -d
```

Open:

```text
http://localhost:8080
```

If the DAG is paused, toggle it on. In Airflow, a paused DAG means the schedule is disabled. Manual triggering can still be used for a demo, but enabling it shows that the pipeline is production-scheduled.

Optional: if you already have the source CSV locally, run a smaller demo month so the recording is not too long:

```powershell
python src/pipeline_runner.py --year 2023 --month 1 --skip-download
```

## Screen-By-Screen Recording Plan

### 1. Login Screen

Action: open Airflow and log in with `admin / admin`.

Voiceover:

"This is the operational dashboard for my flight delay data pipeline. I use Apache Airflow to schedule, monitor, and troubleshoot the full ETL workflow."

### 2. DAGs List Screen

Action: point to the DAG named `flight_delay_pipeline`.

Explain:

- DAG means Directed Acyclic Graph.
- It is the full workflow definition.
- The schedule is monthly: `0 6 5 * *`, meaning the pipeline runs at 6:00 UTC on the 5th of every month.
- `catchup=False` prevents Airflow from automatically running old missed months.
- `max_active_runs=1` prevents overlapping pipeline runs.

Voiceover:

"Here I can see the registered workflows. The important one is `flight_delay_pipeline`. It runs monthly because BTS flight data is published with a delay, so the workflow processes the previous available month instead of assuming today's data is ready."

### 3. DAG Details Header

Action: open `flight_delay_pipeline`.

Explain these common buttons:

- Pause/unpause toggle: turns scheduled runs on or off.
- Trigger/play button: starts a manual run.
- Refresh button: reloads the dashboard state.
- Graph/Grid tabs: different ways to inspect the same pipeline.

Voiceover:

"At the top, Airflow gives me the controls for this workflow. The toggle controls whether the schedule is active. The trigger button lets me run the pipeline manually, which is useful for testing, backfills, or demos."

### 4. Graph View

Action: click Graph view.

Explain the workflow:

```text
start
  -> check_already_processed
  -> extract.download_bts_data
  -> transform.clean_data
  -> quality.run_quality_checks
  -> load.load_to_warehouse
  -> load.refresh_materialized_views
  -> end
```

Also explain the skip branch:

```text
check_already_processed -> already_processed -> end
```

Voiceover:

"The graph shows the complete pipeline dependency order. First, the workflow checks whether this month is already loaded. If the data already exists, it safely skips the load path. If not, it downloads raw BTS data, cleans it with Pandas, runs data quality checks, loads PostgreSQL, refreshes materialized views, and finishes."

### 5. Task Status Signals

Action: point to colored task boxes in Graph or Grid view.

Explain:

- Green: success.
- Red: failed.
- Running/queued colors: task is active or waiting.
- Skipped: Airflow intentionally skipped a branch.
- Up for retry: task failed once but Airflow will retry automatically.

Voiceover:

"The colors are the health signals. Green means the task completed successfully. Red means it failed and needs investigation. A skipped state is not always bad here, because this DAG intentionally skips the extract/load path when data already exists. Airflow also supports retries, and this DAG is configured to retry failed tasks twice."

### 6. Manual Trigger

Action: click Trigger DAG.

Voiceover:

"For the demo, I trigger a run manually. In production this would happen on the schedule, but a manual trigger is perfect for validating the workflow end to end."

### 7. Grid View

Action: click Grid view and show the run row.

Explain:

- Each row is a DAG run.
- Each square is a task instance.
- This view is best for checking run history.

Voiceover:

"Grid view is useful when I want to compare runs over time. Each row is one pipeline run, and each task cell shows whether that step passed, failed, skipped, or is still running."

### 8. Task Logs

Action: click a task, then open Logs.

Explain per task:

- `check_already_processed`: prevents duplicate warehouse rows.
- `download_bts_data`: downloads the BTS monthly CSV.
- `clean_data`: renames columns, casts types, handles nulls, creates `is_delayed`, `delay_category`, `route`, and `date_id`.
- `run_quality_checks`: validates completeness, ranges, uniqueness, no future dates, and delay consistency.
- `load_to_warehouse`: loads carrier/airport dimensions and `warehouse.fact_flights`.
- `refresh_materialized_views`: refreshes fast analytics views.

Voiceover:

"Task logs are where I debug the pipeline. For example, the transform step shows how many rows were cleaned and rejected. The quality step prints a report with pass rates. The load step shows row counts and batch progress into PostgreSQL."

### 9. Code View

Action: click Code tab if available.

Explain:

- This shows the Python DAG code behind the workflow.
- Airflow UI is connected directly to version-controlled code.

Voiceover:

"This is not a manually drawn workflow. The dashboard is generated from Python code in the repository, so the schedule, retries, dependencies, and task functions are all version controlled."

### 10. Analytics Output

Action: show SQL file or terminal query results.

Best outputs to show:

- Carrier on-time ranking.
- Monthly delay trends.
- Worst routes by average delay.
- Day-of-week delay pattern.
- Delay cause breakdown.
- Pipeline health view.

Voiceover:

"After the load step, the data is available for analysis. The warehouse includes materialized views for monthly summary, carrier performance, route analysis, and pipeline health. These views make dashboards faster because common aggregations are precomputed."

## Full Voiceover Script

"Hi everyone, this is my Flight Delay Analysis Pipeline, a data engineering project built with Python, PostgreSQL, Docker, and Apache Airflow.

The goal of this project is to process US flight delay data from the Bureau of Transportation Statistics. The raw files can contain hundreds of thousands of records per month, so the pipeline automates the full process: extract, transform, validate, load, and monitor.

This screen is Apache Airflow. I use it as the operational dashboard for the pipeline. The workflow is called `flight_delay_pipeline`. It is scheduled to run monthly, on the 5th day of the month at 6:00 UTC, because the source data is published after the month has ended.

At the top of the dashboard, the toggle controls whether the schedule is active. The trigger button lets me start a manual run. That is useful for testing, backfills, or demonstrations like this one.

In Graph view, we can see the full workflow. It starts by checking whether the target month has already been processed. This is important for idempotency, which means rerunning the pipeline should not create duplicate rows.

If the data already exists, the workflow goes to the `already_processed` branch and finishes safely. If the data does not exist, it continues to extraction.

The extract task downloads the monthly BTS flight data file. Then the transform task cleans the raw CSV using Pandas. It renames the source columns, converts strings into dates and numbers, handles cancelled flights correctly, removes duplicates, validates airport codes, and creates useful analysis columns like `is_delayed`, `delay_category`, `route`, and `date_id`.

Next is the data quality step. This is where the pipeline checks that critical fields are not null, delay and distance values are within realistic ranges, flight dates are not in the future, and the flight key is mostly unique. It also checks that delay components are consistent with the total arrival delay.

If quality checks fail, the task fails and Airflow marks it red. That protects the warehouse from bad data. If everything passes, the workflow moves to the load step.

The load task writes the clean data into PostgreSQL. It updates dimension tables for carriers and airports, then loads the main fact table, `warehouse.fact_flights`, in batches for better performance.

After loading, the final task refreshes materialized views. These views power faster analysis, such as monthly delay trends, carrier performance, route analysis, and pipeline health.

The colors in Airflow are the health signals. Green means success. Red means failure. Skipped can be expected when the pipeline intentionally avoids duplicate processing. This makes it easy to monitor the whole system at a glance.

In Grid view, I can inspect historical runs. Each row is one run, and each cell is a task result. If something fails, I can open the task logs to see the exact error, row counts, quality report, and batch progress.

The result is a repeatable data pipeline that turns raw aviation data into a structured warehouse ready for analytics. It demonstrates orchestration, data quality, idempotent loading, SQL modeling, and production-style monitoring."

## Short LinkedIn Caption

"Built a flight delay ETL pipeline with Python, PostgreSQL, Docker, and Apache Airflow.

In this walkthrough, I show how the Airflow dashboard monitors the full workflow: extract BTS data, clean it with Pandas, run quality checks, load PostgreSQL, and refresh analytics views.

Key concepts: ETL, orchestration, idempotency, data quality, materialized views, warehouse modeling."

## Tools To Record And Edit

Simple free workflow:

1. Record screen and microphone with OBS Studio.
2. Trim and add captions with CapCut.
3. Export MP4 and upload to LinkedIn.

More polished AI workflow:

1. Record screen with OBS Studio or Descript.
2. Record or generate narration in Descript.
3. Use Descript Studio Sound or a similar cleanup tool.
4. Add captions in CapCut or Descript.
5. Use Canva only for a title card or closing slide.

Suggested settings:

- Resolution: 1920x1080.
- Frame rate: 30 fps.
- Audio: clear microphone, low background noise.
- Length: 2 to 3 minutes.
- Captions: enabled, because many LinkedIn viewers watch muted.

## Recording Checklist

- Airflow opens at `http://localhost:8080`.
- `flight_delay_pipeline` appears in the DAG list.
- The DAG has no import errors.
- Graph view shows all task groups.
- At least one run is visible in Grid view.
- At least one task log opens successfully.
- The final run state is green or you explain why a branch is skipped.
- The video ends with the business value: clean warehouse data ready for analytics.

