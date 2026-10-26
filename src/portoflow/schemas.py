import pyarrow as pa
from .contracts import load_contracts

def observations_schema():
    strings = {"trip_id", "edge_id", "day_group", "time_bucket", "time_inference_flag", "quality_flag", "graph_version", "split"}
    ints = {"taxi_id", "traversal_idx", "gap_index", "gap_edge_count"}
    columns = ["trip_id", "taxi_id", "edge_id", "traversal_idx", "gap_index", "estimated_entry_utc", "estimated_exit_utc",
               "observed_or_inferred_duration_s", "traveled_distance_m", "estimated_speed_kmh", "local_date", "day_group",
               "time_bucket", "time_inference_flag", "gap_edge_count", "quality_flag", "graph_version", "split"]
    return pa.schema([pa.field(name, pa.string() if name in strings else pa.int64() if name in ints else
                              pa.date32() if name == "local_date" else pa.timestamp("us", tz="UTC") if name.startswith("estimated_") and name.endswith("utc") else pa.float64(), False)
                      for name in columns], metadata={b"schema_version": load_contracts()["schema_version"].encode()})

def observation_schema():
    return observations_schema().append(pa.field("complete_trip_evidence", pa.bool_(), False))
