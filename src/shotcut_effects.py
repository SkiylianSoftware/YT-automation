from __future__ import annotations

from collections import namedtuple
from decimal import Decimal
from pathlib import Path
from typing import Callable, ClassVar, Literal, TypeVar
from xml.etree.ElementTree import Element, SubElement

T = TypeVar("T")
rgb = namedtuple("rgb", ["r", "g", "b"], defaults=[255, 255, 255])
rgba = namedtuple("rgba", ["r", "g", "b", "a"], defaults=[255, 255, 255, 255])
rgb_diff = namedtuple("rgb_offset", ["r", "g", "b"], defaults=[0, 0, 0])


def parse_time(t: str) -> Decimal:
    h, m, s = t.split(":")
    return Decimal(h) * 3600 + Decimal(m) * 60 + Decimal(s)


def format_time(seconds: Decimal) -> str:
    h, residue = divmod(seconds, 3600)
    m, s = divmod(residue, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}"


def _property(element: Element, name: str, default: T) -> T:
    val = element.find(f"property[@name='{name}']")
    if val is not None and val.text is not None:
        return type(default)(val.text)
    return default


def clamp(value: float | int | str, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, float(value)))


def clampstr(value: float | int | str, minimum: float, maximum: float) -> str:
    return str(min(maximum, max(minimum, float(value))))


class Filter:
    _property_spec: ClassVar[dict[str, str | Callable]] = {}

    def __init__(self, index: int, mlt_service: str):
        self.index = index
        self.mlt_service = mlt_service

    def to_xml(self, duration: Decimal) -> Element:
        elem = Element("filter", {"id": f"filter{self.index}", "out": format_time(duration)})
        SubElement(elem, "property", {"name": "mlt_service"}).text = self.mlt_service
        for name, value in self._property_spec.items():
            val = value(self) if callable(value) else value
            SubElement(elem, "property", {"name": name}).text = str(val)
        return elem

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        index = int(elem.attrib["id"].removeprefix("filter"))

        shotcut_filter = _property(elem, "shotcut:filter", "")
        if shotcut_filter and (found := FILTER_MAP.get(shotcut_filter)):
            return found.from_xml(elem)

        service = _property(elem, "mlt_service", "")
        if service and (found := SERVICE_MAP.get(service)):
            return found.from_xml(elem)

        return cls(index, service)


class Brightness(Filter):
    def __init__(self, index: int, brightness: float):
        super().__init__(index, "brightness")
        self.brightness = brightness

    _property_spec = {
        "start": "1",
        "level": lambda self: clampstr(self.brightness, 0, 2),
        "rgb_only": "1",
        "shotcut:animIn": "0",
        "shotcut:animOut": "0",
    }

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        return cls(
            int(elem.attrib["id"].removeprefix("filter")),
            clamp(_property(elem, "level", 1.0), 0, 2),
        )


class ColourGrading(Filter):
    def __init__(self, index: int, shadows: rgb_diff, midtones: rgb_diff, gain: rgb_diff):
        super().__init__(index, "lift_gamma_gain")
        self.shadows = shadows
        self.midtones = midtones
        self.gain = gain

    _property_spec = {
        "lift_r": lambda self: clampstr(self.shadows.r, -1, 1),
        "lift_g": lambda self: clampstr(self.shadows.g, -1, 1),
        "lift_b": lambda self: clampstr(self.shadows.b, -1, 1),
        "gamma_r": lambda self: clampstr(self.midtones.r, -1, 1),
        "gamma_g": lambda self: clampstr(self.midtones.g, -1, 1),
        "gamma_b": lambda self: clampstr(self.midtones.b, -1, 1),
        "gain_r": lambda self: clampstr(self.gain.r, -1, 1),
        "gain_g": lambda self: clampstr(self.gain.g, -1, 1),
        "gain_b": lambda self: clampstr(self.gain.b, -1, 1),
        "shotcut:filter_version": "1",
    }

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        shadows = rgb_diff(
            r=clamp(_property(elem, "lift_r", 0.0), -1, 1),
            g=clamp(_property(elem, "lift_g", 0.0), -1, 1),
            b=clamp(_property(elem, "lift_b", 0.0), -1, 1),
        )
        midtones = rgb_diff(
            r=clamp(_property(elem, "gamma_r", 0.0), -1, 1),
            g=clamp(_property(elem, "gamma_g", 0.0), -1, 1),
            b=clamp(_property(elem, "gamma_b", 0.0), -1, 1),
        )
        gain = rgb_diff(
            r=clamp(_property(elem, "gain_r", 0.0), -1, 1),
            g=clamp(_property(elem, "gain_g", 0.0), -1, 1),
            b=clamp(_property(elem, "gain_b", 0.0), -1, 1),
        )
        return ColourGrading(int(elem.attrib["id"].removeprefix("filter")), shadows, midtones, gain)


class Contrast(Filter):
    def __init__(self, index: int, gain: float):
        super().__init__(index, "lift_gamma_gain")
        self.gain = gain

    _property_spec = {
        "lift_r": "0",
        "lift_g": "0",
        "lift_b": "0",
        "gamma_r": lambda self: str(2 - clamp(self.gain, -1, 1)),
        "gamma_g": lambda self: str(2 - clamp(self.gain, -1, 1)),
        "gamma_b": lambda self: str(2 - clamp(self.gain, -1, 1)),
        "gain_r": lambda self: str(clamp(self.gain, -1, 1)),
        "gain_g": lambda self: str(clamp(self.gain, -1, 1)),
        "gain_b": lambda self: str(clamp(self.gain, -1, 1)),
        "shotcut:filter": "contrast",
    }

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        gain = _property(elem, "gain_r", 0.0)
        return cls(int(elem.attrib["id"].removeprefix("filter")), clamp(gain, 0, 2))


_AUDIO_BASE = {"window": "75", "max_gain": "20dB", "channel_mask": "-1"}


class FadeInAudio(Filter):
    def __init__(self, index: int, duration: Decimal, type: Literal["natural", "s-curve", "fast-slow", "slow-fast"]):
        super().__init__(index, "volume")
        self.duration = duration
        self.type = type

    def to_xml(self, clip_duration: Decimal) -> Element:
        elem = super().to_xml(clip_duration)
        level_text = format_time(Decimal(0))
        match self.type:
            case "natural":
                pass
            case "s-curve":
                level_text += "l"
            case "fast-slow":
                level_text += "k"
            case "slow-fast":
                level_text += "j"
        level_text += f"=-60;{format_time(self.duration - Decimal(1) / Decimal(60))}=0"
        SubElement(elem, "property", {"name": "level"}).text = level_text
        SubElement(elem, "property", {"name": "shotcut:filter"}).text = "fadeInVolume"
        SubElement(elem, "property", {"name": "shotcut:animIn"}).text = format_time(self.duration)
        for name, val in _AUDIO_BASE.items():
            SubElement(elem, "property", {"name": name}).text = val
        return elem

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        start, _ = _property(elem, "level", "00:00:00.000=-60;00:00:00.000=0").split(";", 1)
        match start.split("=")[0][-1]:
            case "l":
                level = "s-curve"
            case "k":
                level = "fast-slow"
            case "j":
                level = "slow-fast"
            case _:
                level = "natural"
        return cls(int(elem.attrib["id"].removeprefix("filter")), parse_time(_property(elem, "shotcut:animIn", "00:00:01.000")), level)


class FadeOutAudio(Filter):
    def __init__(self, index: int, duration: Decimal, type: Literal["natural", "s-curve", "fast-slow", "slow-fast"]):
        super().__init__(index, "volume")
        self.duration = duration
        self.type = type

    def to_xml(self, clip_duration: Decimal) -> Element:
        elem = super().to_xml(clip_duration)
        level_text = format_time(clip_duration - self.duration + Decimal(1) / Decimal(60))
        match self.type:
            case "natural":
                pass
            case "s-curve":
                level_text += "l"
            case "fast-slow":
                level_text += "k"
            case "slow-fast":
                level_text += "j"
        level_text += f"=0;{format_time(clip_duration)}=-60"
        SubElement(elem, "property", {"name": "level"}).text = level_text
        SubElement(elem, "property", {"name": "shotcut:filter"}).text = "fadeOutVolume"
        SubElement(elem, "property", {"name": "shotcut:animOut"}).text = format_time(self.duration)
        for name, val in _AUDIO_BASE.items():
            SubElement(elem, "property", {"name": name}).text = val
        return elem

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        start, _ = _property(elem, "level", "00:00:00.000=0;00:00:00.000=-60").split(";", 1)
        match start.split("=")[0][-1]:
            case "l":
                level = "s-curve"
            case "k":
                level = "fast-slow"
            case "j":
                level = "slow-fast"
            case _:
                level = "natural"
        return cls(int(elem.attrib["id"].removeprefix("filter")), parse_time(_property(elem, "shotcut:animOut", "00:00:01.000")), level)


class Gain(Filter):
    def __init__(self, index: int, level: float = 0):
        super().__init__(index, "volume")
        self.level = level

    _property_spec = {
        "window": "75",
        "max_gain": "20dB",
        "level": lambda self: str(self.level),
        "channel_mask": "-1",
        "shotcut:filter": "audioGain",
    }

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        return cls(int(elem.attrib["id"].removeprefix("filter")), float(_property(elem, "level", "0")))


class Mute(Filter):
    def __init__(self, index: int):
        super().__init__(index, "volume")

    _property_spec = {
        "window": "75",
        "max_gain": "20dB",
        "channel_mask": "-1",
        "shotcut:filter": "muteVolume",
        "gain": "0",
    }

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        return cls(int(elem.attrib["id"].removeprefix("filter")))


class FadeInVideo(Filter):
    def __init__(self, index: int, duration: Decimal):
        super().__init__(index, "brightness")
        self.duration = duration

    _property_spec = {
        "start": "1",
        "alpha": "1",
        "shotcut:filter": "fadeInBrightness",
    }

    def to_xml(self, clip_duration: Decimal) -> Element:
        elem = super().to_xml(clip_duration)
        anim_end = format_time(self.duration - Decimal(1) / Decimal(60))
        SubElement(elem, "property", {"name": "level"}).text = f"00:00:00.000=0;{anim_end}=1"
        SubElement(elem, "property", {"name": "shotcut:animIn"}).text = format_time(self.duration)
        return elem

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        return cls(int(elem.attrib["id"].removeprefix("filter")), parse_time(_property(elem, "shotcut:animIn", "00:00:01.000")))


class FadeOutVideo(Filter):
    def __init__(self, index: int, duration: Decimal):
        super().__init__(index, "brightness")
        self.duration = duration

    _property_spec = {
        "start": "1",
        "alpha": "1",
        "shotcut:filter": "fadeOutBrightness",
    }

    def to_xml(self, clip_duration: Decimal) -> Element:
        elem = super().to_xml(clip_duration)
        anim_start = format_time(clip_duration - self.duration + Decimal(1) / Decimal(60))
        SubElement(elem, "property", {"name": "level"}).text = f"{anim_start}=1;{format_time(clip_duration)}=0"
        SubElement(elem, "property", {"name": "shotcut:animOut"}).text = format_time(self.duration)
        return elem

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        return cls(int(elem.attrib["id"].removeprefix("filter")), parse_time(_property(elem, "shotcut:animOut", "00:00:01.000")))


class Opacity(Filter):
    def __init__(self, index: int, opacity: float = 1.0):
        super().__init__(index, "brightness")
        self.opacity = opacity

    _property_spec = {
        "start": "1",
        "level": lambda self: str(self.opacity),
        "shotcut:filter": "brightnessOpacity",
        "alpha": "1",
        "opacity": lambda self: str(self.opacity),
        "rgb_only": "1",
        "shotcut:animIn": "0",
        "shotcut:animOut": "0",
    }

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        return cls(int(elem.attrib["id"].removeprefix("filter")), float(_property(elem, "opacity", "1.0")))


class SizePositionRotate(Filter):
    def __init__(self, index: int, rect: tuple[int, int, int, int] = (0, 0, 1920, 1080), background: str = "#00000000", halign: str = "center", valign: str = "middle"):
        super().__init__(index, "affine")
        self.rect = rect
        self.background = background
        self.halign = halign
        self.valign = valign

    _property_spec = {
        "shotcut:filter": "affineSizePosition",
        "transition.fix_rotate_x": "0",
        "transition.fill": "1",
        "transition.distort": "0",
        "transition.threads": "0",
        "shotcut:animIn": "00:00:00.000",
        "shotcut:animOut": "00:00:00.000",
    }

    def to_xml(self, duration: Decimal) -> Element:
        elem = super().to_xml(duration)
        SubElement(elem, "property", {"name": "background"}).text = self._background_str
        SubElement(elem, "property", {"name": "transition.rect"}).text = self._rect_str
        SubElement(elem, "property", {"name": "transition.halign"}).text = self.halign
        SubElement(elem, "property", {"name": "transition.valign"}).text = self.valign
        return elem

    @property
    def _rect_str(self) -> str:
        return f"{self.rect[0]} {self.rect[1]} {self.rect[2]} {self.rect[3]} 1"

    @property
    def _background_str(self) -> str:
        return f"color:{self.background}" if not self.background.startswith("color:") else self.background

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        r = _property(elem, "transition.rect", "0 0 1920 1080 1")
        parts = r.split()
        rect = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        bg = _property(elem, "background", "color:#00000000")
        if bg.startswith("color:"):
            bg = bg[6:]
        return cls(
            int(elem.attrib["id"].removeprefix("filter")),
            rect=rect,
            background=bg,
            halign=_property(elem, "transition.halign", "center"),
            valign=_property(elem, "transition.valign", "middle"),
        )


_TEXT_BASE = {
    "family": "Sans", "size": "48", "weight": "400",
    "style": "normal", "fgcolour": "0x000000ff",
    "bgcolour": "#00000000", "olcolour": "0x00000000",
    "pad": "0", "halign": "left", "valign": "top",
    "outline": "0", "pixel_ratio": "1", "opacity": "1",
    "typewriter": "0",
    "typewriter.step_length": "25", "typewriter.step_sigma": "0",
    "typewriter.random_seed": "0", "typewriter.macro_type": "1",
    "typewriter.cursor": "1", "typewriter.cursor_blink_rate": "25",
    "typewriter.cursor_char": "|",
    "shotcut:animIn": "00:00:00.000", "shotcut:animOut": "00:00:00.000",
}


class RichText(Filter):
    def __init__(self, index: int, html: str = "", geometry: tuple[int, int, int, int] = (192, 108, 1536, 864)):
        super().__init__(index, "qtext")
        self.html = html
        self.geometry = geometry

    _property_spec = dict(_TEXT_BASE)
    _property_spec.update({
        "argument": "",
        "shotcut:filter": "richText",
        "geometry": lambda self: f"{self.geometry[0]} {self.geometry[1]} {self.geometry[2]} {self.geometry[3]} 1",
        "html": lambda self: self.html,
    })

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        g = _property(elem, "geometry", "192 108 1536 864 1")
        parts = g.split()
        geom = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        return cls(
            int(elem.attrib["id"].removeprefix("filter")),
            html=_property(elem, "html", ""),
            geometry=geom,
        )


class Typewriter(Filter):
    def __init__(self, index: int, text: str = "", geometry: tuple[int, int, int, int] = (0, 0, 1920, 1080), step_length: int = 8, step_sigma: int = 2):
        super().__init__(index, "qtext")
        self.text = text
        self.geometry = geometry
        self.step_length = step_length
        self.step_sigma = step_sigma

    _property_spec = {
        "family": "monospace", "size": "76", "weight": "400",
        "style": "normal", "fgcolour": "#ff00ff00",
        "bgcolour": "#00000000", "olcolour": "#aa000000",
        "pad": "0", "halign": "center", "valign": "middle",
        "outline": "0", "pixel_ratio": "1", "opacity": "1",
        "typewriter": "1",
        "typewriter.random_seed": "0", "typewriter.macro_type": "1",
        "typewriter.cursor": "1", "typewriter.cursor_blink_rate": "25",
        "typewriter.cursor_char": "|",
        "shotcut:animIn": "00:00:00.000", "shotcut:animOut": "00:00:00.000",
        "shotcut:filter": "typewriter",
        "shotcut:usePointSize": "1", "shotcut:pointSize": "57",
        "argument": lambda self: self.text,
        "geometry": lambda self: f"{self.geometry[0]} {self.geometry[1]} {self.geometry[2]} {self.geometry[3]} 1",
        "typewriter.step_length": lambda self: str(self.step_length),
        "typewriter.step_sigma": lambda self: str(self.step_sigma),
    }

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        g = _property(elem, "geometry", "0 0 1920 1080 1")
        parts = g.split()
        geom = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        return cls(
            int(elem.attrib["id"].removeprefix("filter")),
            text=_property(elem, "argument", ""),
            geometry=geom,
            step_length=int(_property(elem, "typewriter.step_length", "8")),
            step_sigma=int(_property(elem, "typewriter.step_sigma", "2")),
        )


class Timer(Filter):
    def __init__(self, index: int, format: str = "SS.SS", start: str = "00:00:00.000", duration: str = "00:00:10.000", speed: float = 1.0, direction: str = "up", geometry: tuple[int, int, int, int] = (0, 0, 1920, 1080)):
        super().__init__(index, "timer")
        self.format = format
        self.start = start
        self.duration = duration
        self.speed = speed
        self.direction = direction
        self.geometry = geometry

    _property_spec = {
        "family": "Sans", "size": "1080", "weight": "400",
        "style": "normal", "fgcolour": "#ffffffff",
        "bgcolour": "#00000000", "olcolour": "#ff000000",
        "pad": "0", "halign": "right", "valign": "bottom",
        "outline": "0", "opacity": "1.0",
        "shotcut:filter": "timer",
        "shotcut:usePointSize": "0",
        "offset": "00:00:00.000",
        "format": lambda self: self.format,
        "start": lambda self: self.start,
        "duration": lambda self: self.duration,
        "speed": lambda self: str(self.speed),
        "direction": lambda self: self.direction,
        "geometry": lambda self: f"{self.geometry[0]} {self.geometry[1]} {self.geometry[2]} {self.geometry[3]} 1",
    }

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        g = _property(elem, "geometry", "0 0 1920 1080 1")
        parts = g.split()
        geom = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        return cls(
            int(elem.attrib["id"].removeprefix("filter")),
            format=_property(elem, "format", "SS.SS"),
            start=_property(elem, "start", "00:00:00.000"),
            duration=_property(elem, "duration", "00:00:10.000"),
            speed=float(_property(elem, "speed", "1")),
            direction=_property(elem, "direction", "up"),
            geometry=geom,
        )


class WhiteBalance(Filter):
    def __init__(self, index: int, color: str = "#7f7f7f", strength: float = 0.433333):
        super().__init__(index, "frei0r.colgate")
        self.color = color
        self.strength = strength

    _property_spec = {
        "version": "0.1",
        "threads": "0",
        "0": lambda self: self.color,
        "1": lambda self: str(self.strength),
    }

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        return cls(
            int(elem.attrib["id"].removeprefix("filter")),
            color=_property(elem, "0", "#7f7f7f"),
            strength=float(_property(elem, "1", "0.433333")),
        )


FILTER_MAP: dict[str, type[Filter]] = {
    "fadeInBrightness": FadeInVideo,
    "fadeOutBrightness": FadeOutVideo,
    "brightnessOpacity": Opacity,
    "contrast": Contrast,
    "fadeInVolume": FadeInAudio,
    "fadeOutVolume": FadeOutAudio,
    "audioGain": Gain,
    "muteVolume": Mute,
    "affineSizePosition": SizePositionRotate,
    "richText": RichText,
    "typewriter": Typewriter,
    "timer": Timer,
}

SERVICE_MAP: dict[str, type[Filter]] = {
    "lift_gamma_gain": ColourGrading,
    "brightness": Brightness,
    "frei0r.colgate": WhiteBalance,
}
