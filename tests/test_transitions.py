"""Tests for shotcut_transitions.py — every transition type round-trips correctly."""

from decimal import Decimal
from pathlib import Path
from xml.etree.ElementTree import Element, tostring

import pytest

from src.shotcut_transitions import (
    RESOURCE_MAP,
    AudioTransition,
    BarHorizontal,
    BarnDoorDiagonalNWSE,
    BarnDoorDiagonalSWNE,
    BarnDoorHorizontal,
    BarnDoorVertical,
    BarnVUp,
    BarVertical,
    BoxBottomCentre,
    BoxBottomLeft,
    BoxBottomRight,
    ClockTop,
    Custom,
    Cut,
    DiagonalTopLeft,
    DiagonalTopRight,
    Dissolve,
    DoubleIris,
    IrisBox,
    IrisCircle,
    MatrixSnakeHorizontal,
    MatrixSnakeParallelHorizontal,
    MatrixSnakeParallelVertical,
    MatrixSnakeVertical,
    MatrixWaterfallHorizontal,
    MatrixWaterfallVertical,
    Transition,
    VideoTransitionBase,
    format_time,
    parse_time,
)

DURATION = Decimal("5")


def _roundtrip_xml(elem: Element) -> Element:
    """Serialise to string and re-parse (simulates file I/O)."""
    from xml.etree.ElementTree import fromstring

    raw = tostring(elem, encoding="unicode")
    return fromstring(raw)


# ---------------------------------------------------------------------------
# Transition container
# ---------------------------------------------------------------------------


def make_transition(video=None, audio=None) -> Transition:
    return Transition(
        index=0,
        duration=DURATION,
        clip_start=0,
        clip_start_out=DURATION,
        clip_end=1,
        clip_end_in=Decimal("0"),
        video_transition=video,
        audio_transition=audio,
    )


class TestTransitionContainer:
    def test_video_only(self):
        t = make_transition(video=Dissolve(0))
        xml = t.to_xml()
        assert xml.tag == "tractor"
        assert xml.find("property[@name='shotcut:transition']").text == "lumaMix"

    def test_audio_only(self):
        t = make_transition(audio=AudioTransition(0))
        xml = t.to_xml()
        assert xml.find("property[@name='shotcut:transition']").text == "mix"

    def test_both_video_and_audio(self):
        t = make_transition(video=Dissolve(0), audio=AudioTransition(0))
        xml = t.to_xml()
        assert xml.find("property[@name='shotcut:transition']").text == "lumaMix"

    def test_roundtrip(self):
        t = make_transition(
            video=Dissolve(1), audio=AudioTransition(2, mix_fraction=0.5)
        )
        xml = t.to_xml()
        xml = _roundtrip_xml(xml)
        t2 = Transition.from_xml(xml)
        assert t.index == t2.index
        assert t.duration == t2.duration
        assert t.clip_start == t2.clip_start
        assert t.clip_end == t2.clip_end
        assert t2.video_transition is not None
        assert type(t2.video_transition) is Dissolve
        assert t2.audio_transition is not None
        assert t2.audio_transition.mix == 0.5

    def test_roundtrip_audio_only(self):
        t = make_transition(audio=AudioTransition(0, mix_fraction=-1))
        xml = _roundtrip_xml(t.to_xml())
        t2 = Transition.from_xml(xml)
        assert t2.video_transition is None
        assert t2.audio_transition is not None
        assert t2.audio_transition.is_cross_fade

    def test_two_tracks_in_xml(self):
        t = make_transition(video=Dissolve(0))
        xml = t.to_xml()
        tracks = xml.findall("track")
        assert len(tracks) == 2

    def test_no_transitions(self):
        t = make_transition()
        xml = t.to_xml()
        assert len(xml.findall("transition")) == 0


# ---------------------------------------------------------------------------
# AudioTransition
# ---------------------------------------------------------------------------


class TestAudioTransition:
    def test_cross_fade_default(self):
        at = AudioTransition(0)
        assert at.is_cross_fade
        xml = at.to_xml(DURATION)
        assert xml.find("property[@name='mlt_service']").text == "mix"
        assert xml.find("property[@name='start']").text == "-1"

    def test_mix_fraction(self):
        at = AudioTransition(0, mix_fraction=0.3)
        assert not at.is_cross_fade
        xml = at.to_xml(DURATION)
        assert float(xml.find("property[@name='start']").text) == pytest.approx(0.3)

    def test_roundtrip(self):
        for mix in (-1, 0, 0.5, 1):
            at = AudioTransition(0, mix_fraction=mix)
            xml = _roundtrip_xml(at.to_xml(DURATION))
            at2 = AudioTransition.from_xml(xml)
            assert at2.mix == pytest.approx(mix)

    def test_clamp(self):
        at = AudioTransition(0, mix_fraction=2.5)
        xml = at.to_xml(DURATION)
        assert float(xml.find("property[@name='start']").text) == pytest.approx(1)

    def test_accepts_blanks(self):
        at = AudioTransition(0)
        xml = at.to_xml(DURATION)
        assert xml.find("property[@name='accepts_blanks']").text == "1"

    def test_from_xml_no_start(self):
        xml = Element("transition", {"id": "transition5", "out": "00:00:05.000"})
        from xml.etree.ElementTree import SubElement

        SubElement(xml, "property", {"name": "a_track"}).text = "0"
        SubElement(xml, "property", {"name": "b_track"}).text = "1"
        SubElement(xml, "property", {"name": "mlt_service"}).text = "mix"
        at = AudioTransition.from_xml(xml)
        assert at.mix == -1
        assert at.is_cross_fade


# ---------------------------------------------------------------------------
# Video transitions – every named luma type
# ---------------------------------------------------------------------------

ALL_NAMED_TYPES = list(RESOURCE_MAP.values())

LUMA_TYPES_WITH_EXPECTED = [
    (BarHorizontal, "%luma01.pgm"),
    (BarVertical, "%luma02.pgm"),
    (BarnDoorHorizontal, "%luma03.pgm"),
    (BarnDoorVertical, "%luma04.pgm"),
    (BarnDoorDiagonalSWNE, "%luma05.pgm"),
    (BarnDoorDiagonalNWSE, "%luma06.pgm"),
    (DiagonalTopLeft, "%luma07.pgm"),
    (DiagonalTopRight, "%luma08.pgm"),
    (MatrixWaterfallHorizontal, "%luma09.pgm"),
    (MatrixWaterfallVertical, "%luma10.pgm"),
    (MatrixSnakeHorizontal, "%luma11.pgm"),
    (MatrixSnakeParallelHorizontal, "%luma12.pgm"),
    (MatrixSnakeVertical, "%luma13.pgm"),
    (MatrixSnakeParallelVertical, "%luma14.pgm"),
    (BarnVUp, "%luma15.pgm"),
    (IrisCircle, "%luma16.pgm"),
    (DoubleIris, "%luma17.pgm"),
    (IrisBox, "%luma18.pgm"),
    (BoxBottomRight, "%luma19.pgm"),
    (BoxBottomLeft, "%luma20.pgm"),
    (BoxBottomCentre, "%luma21.pgm"),
    (ClockTop, "%luma22.pgm"),
]


class TestNamedLumaTransitions:
    @pytest.mark.parametrize("klass,expected_resource", LUMA_TYPES_WITH_EXPECTED)
    def test_resource_constant(self, klass, expected_resource):
        assert klass.resource == expected_resource

    @pytest.mark.parametrize("klass", ALL_NAMED_TYPES)
    def test_to_xml_has_resource(self, klass):
        inst = klass(index=0, invert=False, softness=0.2)
        xml = inst.to_xml(DURATION)
        res = xml.find("property[@name='resource']")
        assert res is not None
        assert res.text == klass.resource

    @pytest.mark.parametrize("klass", ALL_NAMED_TYPES)
    def test_roundtrip(self, klass):
        inst = klass(index=3, invert=True, softness=0.5)
        xml = _roundtrip_xml(inst.to_xml(DURATION))
        inst2 = VideoTransitionBase.from_xml(xml)
        assert type(inst2) is klass
        assert inst2.invert == inst.invert
        assert inst2.softness == pytest.approx(inst.softness)

    @pytest.mark.parametrize("klass", ALL_NAMED_TYPES)
    def test_index_preserved(self, klass):
        inst = klass(index=99)
        xml = _roundtrip_xml(inst.to_xml(DURATION))
        inst2 = VideoTransitionBase.from_xml(xml)
        assert inst2.index == 99

    def test_all_types_covered(self):
        assert len(ALL_NAMED_TYPES) == 22


# ---------------------------------------------------------------------------
# Dissolve
# ---------------------------------------------------------------------------


class TestDissolve:
    def test_no_resource(self):
        d = Dissolve(0)
        xml = d.to_xml(DURATION)
        assert xml.find("property[@name='resource']") is None

    def test_from_xml_no_resource(self):
        xml = Element("transition", {"id": "transition0", "out": "00:00:05.000"})
        from xml.etree.ElementTree import SubElement

        SubElement(xml, "property", {"name": "a_track"}).text = "0"
        SubElement(xml, "property", {"name": "b_track"}).text = "1"
        SubElement(xml, "property", {"name": "mlt_service"}).text = "luma"
        d = VideoTransitionBase.from_xml(xml)
        assert type(d) is Dissolve

    def test_roundtrip(self):
        d = Dissolve(5)
        xml = _roundtrip_xml(d.to_xml(DURATION))
        d2 = VideoTransitionBase.from_xml(xml)
        assert type(d2) is Dissolve
        assert d2.index == 5


# ---------------------------------------------------------------------------
# Cut
# ---------------------------------------------------------------------------


class TestCut:
    def test_color_resource_format(self):
        c = Cut(0, cut_fraction=0.5)
        xml = c.to_xml(DURATION)
        res = xml.find("property[@name='resource']").text
        assert res.startswith("color:#")
        # 0.5 * 255 = 127 = 0x7f -> "#7f7f7f"
        assert res == "color:#7f7f7f"

    def test_zero_cut(self):
        c = Cut(0, cut_fraction=0.0)
        xml = c.to_xml(DURATION)
        res = xml.find("property[@name='resource']").text
        assert res == "color:#000000"

    def test_full_cut(self):
        c = Cut(0, cut_fraction=1.0)
        xml = c.to_xml(DURATION)
        res = xml.find("property[@name='resource']").text
        assert res == "color:#ffffff"

    def test_roundtrip(self):
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            c = Cut(2, cut_fraction=frac)
            xml = _roundtrip_xml(c.to_xml(DURATION))
            c2 = VideoTransitionBase.from_xml(xml)
            assert type(c2) is Cut
            assert c2.cut == pytest.approx(c.cut, abs=0.01)

    def test_clamp(self):
        c = Cut(0, cut_fraction=2.0)
        assert c.cut == 1.0


# ---------------------------------------------------------------------------
# Custom
# ---------------------------------------------------------------------------


class TestCustom:
    def test_creates_with_existing_path(self, tmp_path):
        pgm = tmp_path / "custom.pgm"
        pgm.write_text("P5")
        c = Custom(0, path=pgm)
        assert c.resource == str(pgm)

    def test_raises_on_missing_path(self, tmp_path):
        with pytest.raises(AssertionError):
            Custom(0, path=tmp_path / "nonexistent.pgm")

    def test_roundtrip(self, tmp_path):
        pgm = tmp_path / "roundtrip.pgm"
        pgm.write_text("P5")
        c = Custom(1, path=pgm, invert=True, softness=0.7)
        xml = _roundtrip_xml(c.to_xml(DURATION))
        c2 = VideoTransitionBase.from_xml(xml)
        assert type(c2) is Custom
        assert c2.resource == str(pgm)
        assert c2.invert is True
        assert c2.softness == pytest.approx(0.7)

    def test_unknown_resource_becomes_custom(self, tmp_path):
        pgm = tmp_path / "custom.pgm"
        pgm.write_text("P5")
        xml = Element("transition", {"id": "transition0", "out": "00:00:05.000"})
        from xml.etree.ElementTree import SubElement

        SubElement(xml, "property", {"name": "a_track"}).text = "0"
        SubElement(xml, "property", {"name": "b_track"}).text = "1"
        SubElement(xml, "property", {"name": "mlt_service"}).text = "luma"
        SubElement(xml, "property", {"name": "resource"}).text = str(pgm)
        c = VideoTransitionBase.from_xml(xml)
        assert type(c) is Custom
        assert c.resource == str(pgm)


# ---------------------------------------------------------------------------
# Core transition properties (common to all video types)
# ---------------------------------------------------------------------------


class TestVideoTransitionBaseProperties:
    def test_default_values(self):
        vb = VideoTransitionBase(0)
        assert vb.factory == "loader"
        assert vb.invert is False
        assert vb.softness == 0

    def test_to_xml_writes_common_properties(self):
        vb = VideoTransitionBase(0, invert=True, softness=0.5)
        xml = vb.to_xml(DURATION)
        assert xml.find("property[@name='factory']").text == "loader"
        assert xml.find("property[@name='invert']").text == "1"
        assert xml.find("property[@name='softness']").text == "0.5"
        assert xml.find("property[@name='alpha_over']").text == "1"
        assert xml.find("property[@name='progressive']").text == "1"

    def test_factory_roundtrip(self):
        vb = VideoTransitionBase(0)
        xml = _roundtrip_xml(vb.to_xml(DURATION))
        xml.find("property[@name='factory']").text = "custom_factory"
        vb2 = VideoTransitionBase.from_xml(xml)
        assert vb2.factory == "custom_factory"

    def test_softness_default_from_xml(self):
        xml = Element("transition", {"id": "transition0", "out": "00:00:05.000"})
        vb = VideoTransitionBase.from_xml(xml)
        # Dissolve has no resource so softness is not meaningful
        assert vb.softness == 0

    def test_clamp_softness(self):
        vb = VideoTransitionBase(0, softness=2.0)
        xml = vb.to_xml(DURATION)
        assert float(xml.find("property[@name='softness']").text) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# RESOURCE_MAP completeness
# ---------------------------------------------------------------------------


class TestResourceMap:
    def test_all_entries_map_to_named_types(self):
        for res, klass in RESOURCE_MAP.items():
            assert issubclass(klass, VideoTransitionBase)
            assert klass is not VideoTransitionBase

    def test_all_luma_files_covered(self):
        expected = {f"%luma{i:02d}.pgm" for i in range(1, 23)}
        assert set(RESOURCE_MAP.keys()) == expected

    def test_dissolve_not_in_map(self):
        assert Dissolve not in RESOURCE_MAP.values()

    def test_cut_not_in_map(self):
        assert Cut not in RESOURCE_MAP.values()


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestParseFormatTime:
    def test_parse_roundtrip(self):
        cases = ["00:00:00.000", "01:30:15.500", "00:00:00.001", "99:59:59.999"]
        for c in cases:
            assert format_time(parse_time(c)) == c

    def test_format_time_large(self):
        result = format_time(Decimal("99999"))
        assert ":" in result
