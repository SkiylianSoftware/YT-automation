"""Tests for shotcut_effects.py — every filter class round-trips correctly."""

from decimal import Decimal
from xml.etree.ElementTree import Element, fromstring, tostring

import pytest

from src.shotcut_effects import (
    FILTER_MAP,
    SERVICE_MAP,
    Brightness,
    ColourGrading,
    Contrast,
    FadeInAudio,
    FadeOutAudio,
    FadeInVideo,
    FadeOutVideo,
    Filter,
    Gain,
    Mute,
    Opacity,
    RichText,
    SizePositionRotate,
    Timer,
    Typewriter,
    WhiteBalance,
    _property,
    clamp,
    clampstr,
    format_time,
    parse_time,
    rgb_diff,
)

DURATION = Decimal("10")


def _roundtrip_xml(elem: Element) -> Element:
    raw = tostring(elem, encoding="unicode")
    return fromstring(raw)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_parse_format_roundtrip(self):
        cases = ["00:00:00.000", "01:30:15.500", "00:00:00.001", "99:59:59.999"]
        for c in cases:
            assert format_time(parse_time(c)) == c

    def test_clamp(self):
        assert clamp(-5, 0, 1) == 0
        assert clamp(5, 0, 1) == 1
        assert clamp(0.5, 0, 1) == 0.5

    def test_clampstr(self):
        assert clampstr(-5, 0, 1) == "0"
        assert clampstr(5, 0, 1) == "1"

    def test_property_int(self):
        xml = fromstring('<root><property name="x">42</property></root>')
        assert _property(xml, "x", 0) == 42

    def test_property_float(self):
        xml = fromstring('<root><property name="x">3.14</property></root>')
        assert _property(xml, "x", 0.0) == pytest.approx(3.14)

    def test_property_str(self):
        xml = fromstring('<root><property name="x">hello</property></root>')
        assert _property(xml, "x", "") == "hello"

    def test_property_missing(self):
        xml = fromstring("<root></root>")
        assert _property(xml, "missing", 42) == 42

    def test_property_empty_text(self):
        xml = fromstring('<root><property name="x"></property></root>')
        assert _property(xml, "x", 42) == 42


# ---------------------------------------------------------------------------
# Base Filter
# ---------------------------------------------------------------------------


class TestFilter:
    def test_to_xml_basic(self):
        f = Filter(0, "test_service")
        xml = f.to_xml(DURATION)
        assert xml.tag == "filter"
        assert xml.attrib["id"] == "filter0"
        assert xml.find("property[@name='mlt_service']").text == "test_service"

    def test_from_xml(self):
        f = Filter(5, "volume")
        xml = _roundtrip_xml(f.to_xml(DURATION))
        f2 = Filter.from_xml(xml)
        assert f2.index == 5
        assert f2.mlt_service == "volume"

    def test_unknown_service_falls_back(self):
        xml = fromstring(
            '<filter id="filter3" out="00:00:05.000">'
            '<property name="mlt_service">unknown_svc</property>'
            "</filter>"
        )
        f = Filter.from_xml(xml)
        assert type(f) is Filter
        assert f.mlt_service == "unknown_svc"


# ---------------------------------------------------------------------------
# Brightness
# ---------------------------------------------------------------------------


class TestBrightness:
    def test_roundtrip(self):
        for val in (0, 0.5, 1, 1.5, 2):
            b = Brightness(0, brightness=val)
            xml = _roundtrip_xml(b.to_xml(DURATION))
            b2 = Brightness.from_xml(xml)
            assert b2.brightness == pytest.approx(clamp(val, 0, 2))

    def test_to_xml_properties(self):
        b = Brightness(1, brightness=0.8)
        xml = b.to_xml(DURATION)
        assert xml.find("property[@name='mlt_service']").text == "brightness"
        assert xml.find("property[@name='level']").text == "0.8"
        assert xml.find("property[@name='start']").text == "1"
        assert xml.find("property[@name='rgb_only']").text == "1"

    def test_clamp_brightness(self):
        b = Brightness(0, brightness=5)
        xml = b.to_xml(DURATION)
        assert xml.find("property[@name='level']").text == "2"


# ---------------------------------------------------------------------------
# ColourGrading
# ---------------------------------------------------------------------------


class TestColourGrading:
    def test_to_xml_uses_gain(self):
        cg = ColourGrading(
            0,
            shadows=rgb_diff(0.1, -0.2, 0.3),
            midtones=rgb_diff(0.4, -0.5, 0.6),
            gain=rgb_diff(0.7, -0.8, 0.9),
        )
        xml = cg.to_xml(DURATION)
        assert xml.find("property[@name='gain_r']").text == "0.7"
        assert xml.find("property[@name='gain_g']").text == "-0.8"
        assert xml.find("property[@name='gain_b']").text == "0.9"
        assert xml.find("property[@name='lift_r']").text == "0.1"
        assert xml.find("property[@name='gamma_r']").text == "0.4"

    def test_roundtrip(self):
        cg = ColourGrading(
            5,
            shadows=rgb_diff(0.5, -0.3, 0.1),
            midtones=rgb_diff(-0.2, 0.7, 0.0),
            gain=rgb_diff(1.0, -1.0, 0.5),
        )
        xml = _roundtrip_xml(cg.to_xml(DURATION))
        cg2 = ColourGrading.from_xml(xml)
        assert cg2.index == 5
        assert cg2.shadows == cg.shadows
        assert cg2.midtones == cg.midtones
        assert cg2.gain == cg.gain

    def test_dispatch_via_service_map(self):
        cg = ColourGrading(0, rgb_diff(0, 0, 0), rgb_diff(0, 0, 0), rgb_diff(0, 0, 0))
        xml = _roundtrip_xml(cg.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is ColourGrading

    def test_clamp_values(self):
        cg = ColourGrading(
            0,
            shadows=rgb_diff(-2, 2, 0),
            midtones=rgb_diff(0, -2, 2),
            gain=rgb_diff(2, -2, 0),
        )
        xml = cg.to_xml(DURATION)
        assert xml.find("property[@name='lift_r']").text == "-1"
        assert xml.find("property[@name='lift_g']").text == "1"
        assert xml.find("property[@name='gamma_b']").text == "1"
        assert xml.find("property[@name='gain_r']").text == "1"


# ---------------------------------------------------------------------------
# Contrast
# ---------------------------------------------------------------------------


class TestContrast:
    def test_to_xml_uses_contrast_filter(self):
        c = Contrast(0, gain=0.5)
        xml = c.to_xml(DURATION)
        assert xml.find("property[@name='shotcut:filter']").text == "contrast"
        assert xml.find("property[@name='mlt_service']").text == "lift_gamma_gain"

    def test_roundtrip(self):
        for gain in (0, 0.3, 0.5, 0.8, 1):
            c = Contrast(2, gain=gain)
            xml = _roundtrip_xml(c.to_xml(DURATION))
            c2 = Contrast.from_xml(xml)
            assert c2.index == 2
            assert c2.gain == pytest.approx(clamp(gain, 0, 2))

    def test_dispatch_via_filter_map(self):
        c = Contrast(0, gain=0.5)
        xml = _roundtrip_xml(c.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is Contrast

    def test_non_uniform_gain_does_not_crash(self):
        xml = fromstring(
            '<filter id="filter0" out="00:00:05.000">'
            '<property name="mlt_service">lift_gamma_gain</property>'
            '<property name="shotcut:filter">contrast</property>'
            '<property name="gain_r">0.5</property>'
            '<property name="gain_g">0.3</property>'
            '<property name="gain_b">0.7</property>'
            "</filter>"
        )
        c = Contrast.from_xml(xml)
        assert c.gain == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# FadeInAudio / FadeOutAudio
# ---------------------------------------------------------------------------


class TestFadeInAudio:
    @pytest.mark.parametrize("fade_type", ["natural", "s-curve", "fast-slow", "slow-fast"])
    def test_roundtrip(self, fade_type):
        f = FadeInAudio(0, duration=Decimal("2"), type=fade_type)
        xml = _roundtrip_xml(f.to_xml(Decimal("10")))
        f2 = FadeInAudio.from_xml(xml)
        assert f2.index == 0
        assert f2.duration == pytest.approx(Decimal("2"), abs=Decimal("0.02"))
        assert f2.type == fade_type

    def test_shorter_than_clip(self):
        f = FadeInAudio(0, duration=Decimal("1.5"), type="natural")
        xml = f.to_xml(Decimal("10"))
        assert xml.find("property[@name='shotcut:filter']").text == "fadeInVolume"

    def test_anim_in_property(self):
        f = FadeInAudio(0, duration=Decimal("3"), type="natural")
        xml = f.to_xml(Decimal("10"))
        assert xml.find("property[@name='shotcut:animIn']").text == "00:00:03.000"


class TestFadeOutAudio:
    @pytest.mark.parametrize("fade_type", ["natural", "s-curve", "fast-slow", "slow-fast"])
    def test_roundtrip(self, fade_type):
        f = FadeOutAudio(0, duration=Decimal("2"), type=fade_type)
        xml = _roundtrip_xml(f.to_xml(Decimal("10")))
        f2 = FadeOutAudio.from_xml(xml)
        assert f2.index == 0
        assert f2.duration == pytest.approx(Decimal("2"), abs=Decimal("0.02"))
        assert f2.type == fade_type

    def test_anim_out_property(self):
        f = FadeOutAudio(0, duration=Decimal("3"), type="natural")
        xml = f.to_xml(Decimal("10"))
        f2 = xml.find("property[@name='shotcut:animOut']")
        assert f2 is not None
        assert f2.text == "00:00:03.000"


# ---------------------------------------------------------------------------
# Gain / Mute
# ---------------------------------------------------------------------------


class TestGain:
    def test_roundtrip(self):
        g = Gain(0, level=-6)
        xml = _roundtrip_xml(g.to_xml(DURATION))
        g2 = Gain.from_xml(xml)
        assert g2.index == 0
        assert g2.level == -6

    def test_dispatch(self):
        g = Gain(0, level=0)
        xml = _roundtrip_xml(g.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is Gain

    def test_default_level(self):
        g = Gain(0)
        assert g.level == 0


class TestMute:
    def test_roundtrip(self):
        m = Mute(2)
        xml = _roundtrip_xml(m.to_xml(DURATION))
        m2 = Mute.from_xml(xml)
        assert m2.index == 2

    def test_dispatch(self):
        m = Mute(0)
        xml = _roundtrip_xml(m.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is Mute

    def has_gain_zero(self):
        m = Mute(0)
        xml = m.to_xml(DURATION)
        assert xml.find("property[@name='gain']").text == "0"


# ---------------------------------------------------------------------------
# FadeInVideo / FadeOutVideo
# ---------------------------------------------------------------------------


class TestFadeInVideo:
    def test_roundtrip(self):
        fv = FadeInVideo(0, duration=Decimal("2"))
        xml = _roundtrip_xml(fv.to_xml(Decimal("10")))
        fv2 = FadeInVideo.from_xml(xml)
        assert fv2.index == 0
        assert fv2.duration == Decimal("2")

    def test_dispatch(self):
        fv = FadeInVideo(0, duration=Decimal("2"))
        xml = _roundtrip_xml(fv.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is FadeInVideo

    def test_keyframed_level(self):
        fv = FadeInVideo(0, duration=Decimal("2"))
        xml = fv.to_xml(Decimal("10"))
        level = xml.find("property[@name='level']").text
        assert "00:00:00.000=0" in level
        assert "=1" in level


class TestFadeOutVideo:
    def test_roundtrip(self):
        fv = FadeOutVideo(0, duration=Decimal("2"))
        xml = _roundtrip_xml(fv.to_xml(Decimal("10")))
        fv2 = FadeOutVideo.from_xml(xml)
        assert fv2.index == 0
        assert fv2.duration == Decimal("2")

    def test_dispatch(self):
        fv = FadeOutVideo(0, duration=Decimal("2"))
        xml = _roundtrip_xml(fv.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is FadeOutVideo

    def test_keyframed_level(self):
        fv = FadeOutVideo(0, duration=Decimal("2"))
        xml = fv.to_xml(Decimal("10"))
        level = xml.find("property[@name='level']").text
        assert "=1;" in level
        assert "=0" in level


# ---------------------------------------------------------------------------
# Opacity
# ---------------------------------------------------------------------------


class TestOpacity:
    def test_roundtrip(self):
        o = Opacity(3, opacity=0.75)
        xml = _roundtrip_xml(o.to_xml(DURATION))
        o2 = Opacity.from_xml(xml)
        assert o2.index == 3
        assert o2.opacity == pytest.approx(0.75)

    def test_dispatch(self):
        o = Opacity(0, opacity=0.5)
        xml = _roundtrip_xml(o.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is Opacity

    def test_opacity_property(self):
        o = Opacity(0, opacity=0.5)
        xml = o.to_xml(DURATION)
        assert xml.find("property[@name='opacity']").text == "0.5"
        assert xml.find("property[@name='rgb_only']").text == "1"

    def test_default_opacity(self):
        o = Opacity(0)
        assert o.opacity == 1.0


# ---------------------------------------------------------------------------
# SizePositionRotate
# ---------------------------------------------------------------------------


class TestSizePositionRotate:
    def test_roundtrip(self):
        spr = SizePositionRotate(0, rect=(100, 100, 800, 600))
        xml = _roundtrip_xml(spr.to_xml(DURATION))
        spr2 = SizePositionRotate.from_xml(xml)
        assert spr2.index == 0
        assert spr2.rect == (100, 100, 800, 600)

    def test_dispatch(self):
        spr = SizePositionRotate(0)
        xml = _roundtrip_xml(spr.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is SizePositionRotate

    def test_defaults(self):
        spr = SizePositionRotate(0)
        assert spr.rect == (0, 0, 1920, 1080)
        assert spr.halign == "center"
        assert spr.valign == "middle"
        assert spr.background == "#00000000"


# ---------------------------------------------------------------------------
# RichText
# ---------------------------------------------------------------------------


class TestRichText:
    def test_roundtrip(self):
        html = "<p>Hello</p>"
        rt = RichText(0, html=html)
        xml = _roundtrip_xml(rt.to_xml(DURATION))
        rt2 = RichText.from_xml(xml)
        assert rt2.index == 0
        assert rt2.html == html

    def test_dispatch(self):
        rt = RichText(0, html="<p>test</p>")
        xml = _roundtrip_xml(rt.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is RichText

    def test_empty_html(self):
        rt = RichText(0)
        xml = rt.to_xml(DURATION)
        assert xml.find("property[@name='html']").text == ""


# ---------------------------------------------------------------------------
# Typewriter
# ---------------------------------------------------------------------------


class TestTypewriter:
    def test_roundtrip(self):
        tw = Typewriter(0, text="hello world", step_length=12, step_sigma=3)
        xml = _roundtrip_xml(tw.to_xml(DURATION))
        tw2 = Typewriter.from_xml(xml)
        assert tw2.index == 0
        assert tw2.text == "hello world"
        assert tw2.step_length == 12
        assert tw2.step_sigma == 3

    def test_dispatch(self):
        tw = Typewriter(0, text="test")
        xml = _roundtrip_xml(tw.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is Typewriter

    def has_typewriter_flag(self):
        tw = Typewriter(0, text="test")
        xml = tw.to_xml(DURATION)
        assert xml.find("property[@name='typewriter']").text == "1"


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------


class TestTimer:
    def test_roundtrip(self):
        t = Timer(0, format="MM:SS", direction="down", speed=2.0)
        xml = _roundtrip_xml(t.to_xml(DURATION))
        t2 = Timer.from_xml(xml)
        assert t2.index == 0
        assert t2.format == "MM:SS"
        assert t2.direction == "down"
        assert t2.speed == pytest.approx(2.0)

    def test_dispatch(self):
        t = Timer(0)
        xml = _roundtrip_xml(t.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is Timer

    def test_defaults(self):
        t = Timer(0)
        assert t.format == "SS.SS"
        assert t.direction == "up"
        assert t.speed == 1.0


# ---------------------------------------------------------------------------
# WhiteBalance
# ---------------------------------------------------------------------------


class TestWhiteBalance:
    def test_roundtrip(self):
        wb = WhiteBalance(0, color="#ffffff", strength=0.5)
        xml = _roundtrip_xml(wb.to_xml(DURATION))
        wb2 = WhiteBalance.from_xml(xml)
        assert wb2.index == 0
        assert wb2.color == "#ffffff"
        assert wb2.strength == pytest.approx(0.5)

    def test_dispatch_via_service_map(self):
        wb = WhiteBalance(0)
        xml = _roundtrip_xml(wb.to_xml(DURATION))
        f = Filter.from_xml(xml)
        assert type(f) is WhiteBalance

    def test_defaults(self):
        wb = WhiteBalance(0)
        assert wb.color == "#7f7f7f"
        assert wb.strength == pytest.approx(0.433333)

    def test_property_names(self):
        wb = WhiteBalance(0, color="#000000", strength=0.3)
        xml = wb.to_xml(DURATION)
        assert xml.find("property[@name='0']").text == "#000000"
        assert xml.find("property[@name='1']").text == "0.3"
        assert xml.find("property[@name='mlt_service']").text == "frei0r.colgate"


# ---------------------------------------------------------------------------
# Filter dispatch register completeness
# ---------------------------------------------------------------------------


class TestFilterMap:
    def test_all_filter_map_classes_exist(self):
        for name, klass in FILTER_MAP.items():
            assert issubclass(klass, Filter)
            assert klass is not Filter

    def test_all_service_map_classes_exist(self):
        for name, klass in SERVICE_MAP.items():
            assert issubclass(klass, Filter)
            assert klass is not Filter

    def test_contrast_in_filter_map(self):
        assert Contrast in FILTER_MAP.values()

    def test_colour_grading_in_service_map(self):
        assert ColourGrading in SERVICE_MAP.values()

    def test_no_duplicates(self):
        all_classes = list(FILTER_MAP.values()) + list(SERVICE_MAP.values())
        assert len(all_classes) == len(set(all_classes))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_colourgrading_was_crashing_bug(self):
        """Verify the critical bug is fixed — ColourGrading.from_xml with gain."""
        cg = ColourGrading(0, rgb_diff(0, 0, 0), rgb_diff(0, 0, 0), rgb_diff(0, 0, 0))
        xml = _roundtrip_xml(cg.to_xml(DURATION))
        cg2 = ColourGrading.from_xml(xml)
        assert cg2.gain == rgb_diff(0, 0, 0)

    def test_filter_from_xml_without_mlt_service(self):
        xml = fromstring('<filter id="filter0" out="00:00:05.000"></filter>')
        f = Filter.from_xml(xml)
        assert type(f) is Filter

    def test_no_shotcut_filter_property(self):
        xml = fromstring(
            '<filter id="filter0" out="00:00:05.000">'
            '<property name="mlt_service">brightness</property>'
            "</filter>"
        )
        f = Filter.from_xml(xml)
        assert type(f) is Brightness
