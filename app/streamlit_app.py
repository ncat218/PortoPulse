"""Read precomputed historical artifacts only. No preprocessing or matching on app load."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import streamlit as st
from ui_logic import STATUS_LABELS, index_views
from journey_view import render_view

from portoflow.storage import sha256_file, verify_checkpoint

st.set_page_config(page_title="Porto historical taxi patterns", layout="wide")
st.title("PortoFlow · Giao thông lịch sử")
st.caption("Ước lượng từ quỹ đạo taxi lịch sử · Tốc độ trên cạnh được nội suy · Không phải giao thông trực tiếp")
source_details = st.sidebar.expander('Nguồn dữ liệu')
artifact_root = source_details.text_input("Thư mục kết quả", os.environ.get("PORTOFLOW_ARTIFACTS", "runs/current"))
root = Path(artifact_root)
if not (root / "run_metadata.json").is_file():
    st.info("Vùng 10×10 km đã có graph thật. Chưa có kết quả matching toàn Porto trong thư mục đang chọn; chưa hiển thị tốc độ hoặc ETA mới.")
    preview = Path(__file__).resolve().parents[1] / 'data' / 'region_preview.png'
    if preview.is_file():
        st.image(str(preview), caption='Mạng đường vùng nghiên cứu · chưa phải bản đồ giao thông')
    region_file = Path(__file__).resolve().parents[1] / 'data' / 'region.json'
    if region_file.is_file():
        region = json.loads(region_file.read_text(encoding='utf-8'))
        st.write(f"{region['core_directed_edges']:,} cạnh có hướng trong vùng · {region['context_directed_edges']:,} cạnh gồm vùng đệm matching")
    st.caption("Chạy notebook PortoFlow hoặc scripts/run_pipeline.py; sau đó chọn thư mục candidate export để review.")
    st.stop()


@st.cache_resource(max_entries=2)
def load_artifacts(folder: str, modified_ns: int):
    # Shared read-only snapshot: cache_data would unpickle/copy all 12 buckets
    # on every UI event. No app or routing function mutates these records.
    directory = Path(folder)
    metadata = verify_checkpoint(directory)
    table = pq.ParquetFile(directory / "congestion_profiles.parquet").read()
    # Decode the repeated UTC cutoff once per unique instant. Per-scalar timezone
    # conversion is slow on some Windows/PyArrow installations; preserve exact us.
    cutoffs = table.column("train_cutoff").cast("int64").to_pylist()
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    instants = {value: epoch + timedelta(microseconds=value) for value in set(cutoffs)}
    profiles = table.drop(["train_cutoff"]).to_pylist()
    for row, value in zip(profiles, cutoffs):
        row["train_cutoff"] = instants[value]
    geojson = json.loads((directory / "traffic.geojson").read_text(encoding="utf-8"))
    config = json.loads((directory / "pipeline_config.json").read_text(encoding="utf-8"))
    views=index_views(profiles,geojson)
    return metadata, profiles, views, config


try:
    metadata, profiles, views, config = load_artifacts(str(root.resolve()), (root / "run_metadata.json").stat().st_mtime_ns)
except (ValueError, OSError, KeyError) as exc:
    st.error(f"Không đọc được bộ kết quả: {exc}")
    st.stop()
if metadata["data_kind"] == "SYNTHETIC":
    st.warning("SYNTHETIC DEMO — toàn bộ dữ liệu và đường trong bộ này là tổng hợp, không phải kết quả Porto thực.")
else:
    source_details.info("Mẫu taxi lịch sử; nguồn đầu vào và chất lượng matching cần đối chiếu báo cáo kiểm chứng.")
if metadata.get('status', '').startswith('CANDIDATE'):
    st.warning('Kết quả đang chờ review matching và holdout; chưa phải bản nghiệm thu.')
source_details.caption(f"Đồ thị: {metadata['graph_version'][:16]} · Train cutoff UTC: {metadata['cutoff_utc']} · Ngưỡng hỗ trợ đang là cấu hình thí nghiệm")
day = st.sidebar.selectbox("Nhóm ngày", ["weekday", "weekend"])
bucket = st.sidebar.selectbox("Giờ Europe/Lisbon", sorted({key[1] for key in views}))
selected = views[(day,bucket)]['rows']
render_view(metadata,profiles,views[(day,bucket)]['features'],config,root,day,bucket,selected,
            background_features=views[(day,bucket)]['map_features'])

edge_id=st.selectbox('Xem chi tiết cạnh',sorted(row['edge_id'] for row in selected))
record=next(row for row in selected if row['edge_id']==edge_id)
display_record={**record,'status':STATUS_LABELS[record['status']]}
st.dataframe(pd.DataFrame([display_record]).drop(columns=['graph_version']),hide_index=True)
chart=pd.DataFrame([row for row in profiles if row['edge_id']==edge_id and row['day_group']==day])
st.line_chart(chart.set_index('time_bucket')[['median_speed_kmh','reference_speed_kmh']])
st.caption('Đường tham chiếu là một proxy. Tình trạng chưa xác định vẫn được giữ là Chưa xác định.')

with st.expander("Độ phủ và độ bền của kết quả"):
    st.caption("Số cạnh chậm còn phụ thuộc số ngày, số taxi và độ phủ. So sánh hai nhóm ngày cần xét cùng những cạnh đủ dữ liệu.")
    diagnostic_folder = (Path(__file__).resolve().parents[1] / "reports" / "validation" /
                         ("profile_robustness_" + metadata["run_id"]))
    if (diagnostic_folder / "run_metadata.json").is_file():
        try:
            diagnostic_manifest = verify_checkpoint(diagnostic_folder)
            if (diagnostic_manifest["export_run_id"] != metadata["run_id"] or
                    diagnostic_manifest["source_export_manifest_sha256"] != sha256_file(root / "run_metadata.json")):
                raise ValueError("Báo cáo chẩn đoán không thuộc export đang mở")
            diagnostic = json.loads((diagnostic_folder / "summary.json").read_text(encoding="utf-8"))
            if diagnostic["status"] != "COMPLETE_DIAGNOSTICS_ONLY" or not diagnostic["training_only"]:
                raise ValueError("Báo cáo chẩn đoán chưa hoàn tất trên train")
            exposure = diagnostic["exposure"]
            st.dataframe(pd.DataFrame([{"Nhóm ngày": label,
                "Số ngày train có quan sát hợp lệ": len(exposure[label]["dates"]),
                "Số chuyến train có quan sát hợp lệ": exposure[label]["accepted_trips"]}
                for label in ("weekday", "weekend")]), hide_index=True)
            pair = next(r for r in diagnostic["paired_days"] if r["time_bucket"] == bucket)
            st.write(f"Cùng khung {bucket}, có {pair['common_supported_edges']} cạnh đủ dữ liệu ở cả hai nhóm: "
                     f"weekday có {pair['weekday_common_slow']} cạnh chậm, weekend có {pair['weekend_common_slow']} cạnh chậm.")
            agreement = diagnostic["taxi_independent_reference"]["agreement_on_common"]
            if agreement is not None:
                st.warning(f"Hai nhóm taxi cho nhãn trùng nhau {agreement:.1%} trên phần cùng đủ dữ liệu. "
                           "Đây là chẩn đoán độ bền, không phải độ chính xác so với giao thông thực.")
            removal = diagnostic["scenarios"]["without_under_1_kmh"]
            st.caption(f"Phép thử bỏ các quan sát dưới 1 km/h làm {removal['changed_on_common']} tổ hợp cạnh–giờ đổi nhãn "
                       f"và {removal['lost_support']} tổ hợp mất hỗ trợ. Đây chỉ là kiểm độ nhạy: bỏ tốc độ thấp cũng có thể "
                       "bỏ dừng hoặc chậm thật. Bản đồ vẫn dùng cấu hình đã review.")
        except (ValueError, OSError, KeyError, StopIteration) as exc:
            st.info(f"Chưa dùng được báo cáo độ bền cho export này: {exc}")
    else:
        st.info("Chưa có báo cáo độ bền tương ứng với export này. Bản đồ vẫn thể hiện đúng ngưỡng hỗ trợ đã lưu.")
with st.expander("Chẩn đoán và bản dự phòng"):
    st.image(str(root / "diagnostics.png"))
    st.json(json.loads((root / "coverage.json").read_text(encoding="utf-8")))
    st.caption("Lớp nền bản đồ và thư viện JavaScript cần kết nối Internet; bảng và ảnh chẩn đoán vẫn dùng dữ liệu cục bộ.")
