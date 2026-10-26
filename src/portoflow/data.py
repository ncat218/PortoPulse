"""Bounded, streaming Porto CSV/ZIP input. No automatic downloads."""

import csv
import io
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO

RAW_COLUMNS = (
    "TRIP_ID", "CALL_TYPE", "ORIGIN_CALL", "ORIGIN_STAND", "TAXI_ID",
    "TIMESTAMP", "DAYTYPE", "MISSING_DATA", "POLYLINE",
)
HEADER_ALIASES = {"DAY_TYPE": "DAYTYPE"}


def normalize_header(header: list[str]) -> list[str]:
    """Accept only the documented day-type spelling alias; reject ambiguous schemas."""
    canonical = [HEADER_ALIASES.get(name, name) for name in header]
    if len(canonical) != len(RAW_COLUMNS) or set(canonical) != set(RAW_COLUMNS):
        raise ValueError(
            f"Expected exactly Porto's nine columns {RAW_COLUMNS}; got {header}. "
            "The only supported header alias is DAY_TYPE -> DAYTYPE; "
            "missing, extra or duplicate columns are not accepted."
        )
    return canonical


@contextmanager
def open_csv(source: Path, member: str = "train.csv") -> Iterator[TextIO]:
    """Stream a CSV or one exact ZIP member without extracting the archive."""
    if not source.is_file():
        raise FileNotFoundError(
            f"Missing Porto input: {source}. Attach train.csv or train.csv.zip in Kaggle. "
            "Official source: https://archive.ics.uci.edu/dataset/339/"
            "taxi+service+trajectory+prediction+challenge+ecml+pkdd+2015"
        )
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            matches = [info for info in archive.infolist() if info.filename == member]
            if len(matches) != 1:
                raise ValueError(
                    f"ZIP must contain exactly one {member!r}; found "
                    f"{[info.filename for info in archive.infolist()][:20]}. "
                    "If this is the outer UCI bundle, attach/extract its inner train.csv.zip first."
                )
            with archive.open(matches[0]) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                    yield stream
    elif source.suffix.lower() == ".csv":
        with source.open(encoding="utf-8-sig", newline="") as stream:
            yield stream
    else:
        raise ValueError("Input must be .csv or .zip containing the configured CSV member")


def read_batches(
    source: Path, *, batch_size: int, max_rows: int, member: str = "train.csv",
    schema_info: dict | None = None,
) -> Iterator[list[tuple[int, dict]]]:
    """Read a bounded prefix with strict schema validation and an explicit header alias.

    If supplied, schema_info receives the raw/canonical headers and applied aliases.
    Values are never changed; row-width errors remain visible to downstream QC.
    """
    if not 1 <= batch_size <= max_rows <= 5000:
        raise ValueError("S01 small-run budget requires 1 <= batch_size <= max_rows <= 5000")
    yield from _stream_batches(source, batch_size=batch_size, max_rows=max_rows,
                               member=member, schema_info=schema_info)


def _stream_batches(source: Path, *, batch_size: int, max_rows: int, member: str,
                    schema_info: dict | None = None):
    """Shared parser; public workflows must validate their separate budgets first."""
    csv.field_size_limit(16 * 1024 * 1024)
    with open_csv(source, member) as stream:
        reader = csv.DictReader(stream, strict=True)
        header = reader.fieldnames or []
        canonical = normalize_header(header)
        if schema_info is not None:
            schema_info.update({"raw_columns": list(header), "canonical_columns": canonical,
                                "header_aliases_applied": {name: HEADER_ALIASES[name]
                                                           for name in header if name in HEADER_ALIASES}})
        reader.fieldnames = canonical
        batch = []
        # Do not fetch a (max_rows + 1)th data record from the stream.
        for index in range(max_rows):
            try:
                row = next(reader)
            except StopIteration:
                break
            batch.append((index + 1, row))
            if len(batch) == batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
