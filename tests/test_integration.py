"""Integration tests using a real PSG recording (tests/PSG1.edf).

These tests exercise the full read pipeline end-to-end against an actual
polysomnography EDF file, verifying header parsing, signal loading, timestamps,
datetimes, annotations, and selective channel loading.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy
import pytest

from edfplus import Annotation, EDFFile, Signal, read_edf

PSG_FILE = Path("tests/PSG1.edf")
skip_if_missing = pytest.mark.skipif(not PSG_FILE.exists(), reason="PSG test file not available")


@skip_if_missing
class TestPSGIntegration:
    """Integration tests against the real PSG recording."""

    def test_read_edf_returns_edffile(self) -> None:
        """read_edf returns an EDFFile without error."""
        with read_edf(PSG_FILE) as edf:
            assert isinstance(edf, EDFFile)

    def test_header_variant(self) -> None:
        """Header variant is one of the valid EDF variants."""
        with read_edf(PSG_FILE) as edf:
            assert edf.header.variant in ("EDF", "EDF+C", "EDF+D")

    def test_header_num_signals(self) -> None:
        """Header has at least one signal."""
        with read_edf(PSG_FILE) as edf:
            assert edf.header.num_signals >= 1

    def test_header_start_datetime(self) -> None:
        """Header start_datetime is a valid datetime object."""
        with read_edf(PSG_FILE) as edf:
            assert isinstance(edf.header.start_datetime, datetime.datetime)

    def test_signals_non_empty(self) -> None:
        """Signals list is non-empty and all items are Signal instances."""
        with read_edf(PSG_FILE) as edf:
            assert len(edf.signals) > 0
            for sig in edf.signals:
                assert isinstance(sig, Signal)

    def test_signal_samples_lazy_load(self) -> None:
        """Accessing .samples auto-loads from disk with float64 dtype."""
        with read_edf(PSG_FILE) as edf:
            for sig in edf.signals:
                assert sig.samples.size > 0
                assert sig.samples.dtype == numpy.float64

    def test_eager_load_samples(self) -> None:
        """eager_load_samples=True makes .samples accessible immediately."""
        with read_edf(PSG_FILE, eager_load_samples=True) as edf:
            for sig in edf.signals:
                assert sig._samples is not None
                assert sig.samples.size > 0

    def test_signal_sample_rate_positive(self) -> None:
        """All signals have a positive sample rate."""
        with read_edf(PSG_FILE) as edf:
            for sig in edf.signals:
                assert sig.sample_rate > 0

    def test_signal_timestamps_length(self) -> None:
        """Signal.timestamps() length equals len(Signal.samples)."""
        with read_edf(PSG_FILE) as edf:
            for sig in edf.signals:
                ts = sig.timestamps()
                assert len(ts) == len(sig.samples)

    def test_signal_datetimes_length(self) -> None:
        """Signal.datetimes() length equals len(Signal.samples)."""
        with read_edf(PSG_FILE) as edf:
            for sig in edf.signals:
                dt = sig.datetimes()
                assert len(dt) == len(sig.samples)

    def test_annotations_if_edfplus(self) -> None:
        """For EDF+ files, annotations is a list with all items being Annotation instances."""
        with read_edf(PSG_FILE) as edf:
            if edf.header.variant in ("EDF+C", "EDF+D"):
                assert isinstance(edf.annotations, list)
                for ann in edf.annotations:
                    assert isinstance(ann, Annotation)

    def test_signal_load_returns_full_samples(self) -> None:
        """signal.load() with no args returns same as .samples."""
        with read_edf(PSG_FILE) as edf:
            sig = edf.signals[0]
            numpy.testing.assert_array_equal(sig.load(), sig.samples)

    def test_signal_load_by_index(self) -> None:
        """signal.load(start=0, stop=10) returns 10 samples."""
        with read_edf(PSG_FILE) as edf:
            sig = edf.signals[0]
            cropped = sig.load(start=0, stop=10)
            assert len(cropped) == 10

    def test_getitem_by_label(self) -> None:
        """edf['label'].load() works."""
        with read_edf(PSG_FILE) as edf:
            label = edf.signals[0].label
            sig = edf[label]
            assert sig.load(start=0, stop=10).size == 10
