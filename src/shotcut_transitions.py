from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from re import search
from typing import Optional, TypeVar
from xml.etree.ElementTree import Element, SubElement

T = TypeVar("T")


def parse_time(t: str) -> Decimal:
    h, m, s = t.split(":")
    return Decimal(h) * 3600 + Decimal(m) * 60 + Decimal(s)


def format_time(seconds: Decimal) -> str:
    h, residue = divmod(seconds, 3600)
    m, s = divmod(residue, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}"


class Transition:
    def __init__(
        self,
        index: int,
        duration: Decimal,
        clip_start: int,
        clip_start_out: Decimal,
        clip_end: int,
        clip_end_in: Decimal,
        video_transition: Optional[VideoTransitionBase] = None,
        audio_transition: Optional[AudioTransition] = None,
    ):
        self.index = index
        self.duration = duration
        self.clip_start = clip_start
        self.clip_end = clip_end
        self.clip_start_out = clip_start_out
        self.clip_end_in = clip_end_in

        self.video_transition = video_transition
        self.audio_transition = audio_transition

    def to_xml(self) -> Element:
        is_audio_only = (
            self.video_transition is None and self.audio_transition is not None
        )

        tractor = Element(
            "tractor",
            {
                "id": f"tractor{self.index}",
                "in": "00:00:00.000",
                "out": format_time(self.duration),
            },
        )
        SubElement(
            tractor,
            "property",
            {"name": "shotcut:transition"},
        ).text = (
            "mix" if is_audio_only else "lumaMix"
        )
        SubElement(
            tractor,
            "track",
            {
                "producer": f"chain{self.clip_start}",
                "in": format_time(self.clip_start_out - self.duration),
                "out": format_time(self.clip_start_out),
            },
        )
        SubElement(
            tractor,
            "track",
            {
                "producer": f"chain{self.clip_end}",
                "in": format_time(self.clip_end_in),
                "out": format_time(self.clip_end_in + self.duration),
            },
        )
        if self.video_transition is not None:
            tractor.append(self.video_transition.to_xml(duration=self.duration))
        if self.audio_transition is not None:
            tractor.append(self.audio_transition.to_xml(duration=self.duration))
        return tractor

    @staticmethod
    def from_xml(elem: Element) -> Transition:
        tracks = elem.findall("track")
        transitions = elem.findall("transition")
        video = None
        audio = None
        for t in transitions:
            svc = t.find("property[@name='mlt_service']")
            if svc is not None and svc.text is not None and svc.text == "mix":
                audio = AudioTransition.from_xml(t)
            else:
                video = VideoTransitionBase.from_xml(t)

        track1, track2 = tracks[0], tracks[1]

        def _producer_id(producer: str) -> int:
            m = search(r"\d+", producer)
            return int(m.group()) if m else 0

        return Transition(
            index=_producer_id(elem.attrib["id"]),
            duration=parse_time(elem.attrib["out"]) - parse_time(elem.attrib["in"]),
            clip_start=_producer_id(track1.attrib["producer"]),
            clip_start_out=parse_time(track1.attrib["out"]),
            clip_end=_producer_id(track2.attrib["producer"]),
            clip_end_in=parse_time(track2.attrib["in"]),
            video_transition=video,
            audio_transition=audio,
        )


class TransitionBase:
    def __init__(self, index: int, service: str) -> None:
        self.index = index
        self.service = service

    def clamp(self, value: float) -> float:
        return min(1, max(0, value))

    def to_xml(self, duration: Decimal) -> Element:
        transition = Element(
            "transition",
            {"id": f"transition{self.index}", "out": format_time(duration)},
        )
        SubElement(transition, "property", {"name": "a_track"}).text = "0"
        SubElement(transition, "property", {"name": "b_track"}).text = "1"
        SubElement(transition, "property", {"name": "mlt_service"}).text = self.service
        return transition

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> T:
        service = elem.find("property[@name='mlt_service']")
        assert service is not None
        assert service.text is not None

        return cls(
            int(elem.attrib["id"].removeprefix("transition")),
            service.text.lower(),
        )


class AudioTransition(TransitionBase):
    def __init__(
        self,
        index: int,
        mix_fraction: float = -1,
    ) -> None:
        super().__init__(index, "mix")
        self.mix = mix_fraction

    @property
    def is_cross_fade(self) -> bool:
        return self.mix < 0

    def to_xml(self, duration: Decimal) -> Element:
        transition = super().to_xml(duration=duration)
        SubElement(transition, "property", {"name": "start"}).text = str(
            -1 if self.is_cross_fade else self.clamp(self.mix)
        )
        SubElement(transition, "property", {"name": "accepts_blanks"}).text = "1"
        return transition

    @staticmethod
    def from_xml(elem: Element) -> AudioTransition:
        start_elem = elem.find("property[@name='start']")
        start = (
            float(start_elem.text)
            if (start_elem is not None and start_elem.text)
            else -1.0
        )
        return AudioTransition(
            int(elem.attrib["id"].removeprefix("transition")),
            float(start),
        )


class VideoTransitionBase(TransitionBase):
    def __init__(
        self,
        index: int,
        invert: bool = False,
        softness: float = 0,
    ) -> None:
        super().__init__(index, "luma")
        self.factory = "loader"
        self.invert = invert
        self.progressive = "1"
        self.softness = softness

    def to_xml(self, duration: Decimal) -> Element:
        transition = super().to_xml(duration=duration)
        SubElement(transition, "property", {"name": "factory"}).text = self.factory
        SubElement(transition, "property", {"name": "alpha_over"}).text = "1"
        SubElement(transition, "property", {"name": "fix_background_alpha"}).text = "1"
        SubElement(transition, "property", {"name": "progressive"}).text = (
            self.progressive
        )
        SubElement(transition, "property", {"name": "invert"}).text = (
            "1" if self.invert else "0"
        )
        SubElement(transition, "property", {"name": "softness"}).text = str(
            self.clamp(self.softness)
        )
        if res := getattr(self, "resource", None):
            SubElement(transition, "property", {"name": "resource"}).text = str(res)
        return transition

    @classmethod
    def from_xml(cls: type[T], elem: Element) -> VideoTransitionBase:
        index = int(elem.attrib["id"].removeprefix("transition"))
        invert = (
            inv.text == "1"
            if (inv := elem.find("property[@name='invert']")) is not None
            else False
        )
        softness = (
            float(soft.text or "0.2")
            if (soft := elem.find("property[@name='softness']")) is not None
            else 0.2
        )
        factory_elem = elem.find("property[@name='factory']")
        factory = (
            factory_elem.text
            if factory_elem is not None and factory_elem.text
            else "loader"
        )

        resource = elem.find("property[@name='resource']")
        if resource is None or resource.text is None:
            result: VideoTransitionBase = Dissolve(index)
        else:
            restext = resource.text
            assert restext is not None
            if restext.lower().startswith("color"):
                raw = restext.lower().rsplit("#", 1)[1][:2]
                result = Cut(index, int(raw, 16) / 255.0)
            elif Found := RESOURCE_MAP.get(restext):
                result = Found(index=index, invert=invert, softness=softness)
            else:
                result = Custom(
                    index=index,
                    path=Path(restext),
                    invert=invert,
                    softness=softness,
                    validate=False,
                )

        result.factory = factory
        return result


class Dissolve(VideoTransitionBase):
    def __init__(self, index: int):
        super().__init__(index)


class Cut(VideoTransitionBase):
    def __init__(
        self,
        index: int,
        cut_fraction: float,
    ) -> None:
        super().__init__(index=index)
        self.cut = self.clamp(cut_fraction)

    def to_xml(self, duration: Decimal) -> Element:
        transition = super().to_xml(duration=duration)
        val = int(255 * self.clamp(self.cut))
        SubElement(transition, "property", {"name": "resource"}).text = (
            f"color:#{val:02x}{val:02x}{val:02x}"
        )
        return transition


class BarHorizontal(VideoTransitionBase):
    resource = "%luma01.pgm"


class BarVertical(VideoTransitionBase):
    resource = "%luma02.pgm"


class BarnDoorHorizontal(VideoTransitionBase):
    resource = "%luma03.pgm"


class BarnDoorVertical(VideoTransitionBase):
    resource = "%luma04.pgm"


class BarnDoorDiagonalSWNE(VideoTransitionBase):
    resource = "%luma05.pgm"


class BarnDoorDiagonalNWSE(VideoTransitionBase):
    resource = "%luma06.pgm"


class DiagonalTopLeft(VideoTransitionBase):
    resource = "%luma07.pgm"


class DiagonalTopRight(VideoTransitionBase):
    resource = "%luma08.pgm"


class MatrixWaterfallHorizontal(VideoTransitionBase):
    resource = "%luma09.pgm"


class MatrixWaterfallVertical(VideoTransitionBase):
    resource = "%luma10.pgm"


class MatrixSnakeHorizontal(VideoTransitionBase):
    resource = "%luma11.pgm"


class MatrixSnakeParallelHorizontal(VideoTransitionBase):
    resource = "%luma12.pgm"


class MatrixSnakeVertical(VideoTransitionBase):
    resource = "%luma13.pgm"


class MatrixSnakeParallelVertical(VideoTransitionBase):
    resource = "%luma14.pgm"


class BarnVUp(VideoTransitionBase):
    resource = "%luma15.pgm"


class IrisCircle(VideoTransitionBase):
    resource = "%luma16.pgm"


class DoubleIris(VideoTransitionBase):
    resource = "%luma17.pgm"


class IrisBox(VideoTransitionBase):
    resource = "%luma18.pgm"


class BoxBottomRight(VideoTransitionBase):
    resource = "%luma19.pgm"


class BoxBottomLeft(VideoTransitionBase):
    resource = "%luma20.pgm"


class BoxBottomCentre(VideoTransitionBase):
    resource = "%luma21.pgm"


class ClockTop(VideoTransitionBase):
    resource = "%luma22.pgm"


class Custom(VideoTransitionBase):
    def __init__(
        self,
        index: int,
        path: Path,
        invert: bool = False,
        softness: float = 0.2,
        validate: bool = True,
    ) -> None:
        super().__init__(index, invert, softness)
        self.resource = str(path.expanduser())
        if validate:
            assert (
                path.exists()
            ), f"resource {path} does not exist for custom transition"


RESOURCE_MAP: dict[str, type[VideoTransitionBase]] = {
    "%luma01.pgm": BarHorizontal,
    "%luma02.pgm": BarVertical,
    "%luma03.pgm": BarnDoorHorizontal,
    "%luma04.pgm": BarnDoorVertical,
    "%luma05.pgm": BarnDoorDiagonalSWNE,
    "%luma06.pgm": BarnDoorDiagonalNWSE,
    "%luma07.pgm": DiagonalTopLeft,
    "%luma08.pgm": DiagonalTopRight,
    "%luma09.pgm": MatrixWaterfallHorizontal,
    "%luma10.pgm": MatrixWaterfallVertical,
    "%luma11.pgm": MatrixSnakeHorizontal,
    "%luma12.pgm": MatrixSnakeParallelHorizontal,
    "%luma13.pgm": MatrixSnakeVertical,
    "%luma14.pgm": MatrixSnakeParallelVertical,
    "%luma15.pgm": BarnVUp,
    "%luma16.pgm": IrisCircle,
    "%luma17.pgm": DoubleIris,
    "%luma18.pgm": IrisBox,
    "%luma19.pgm": BoxBottomRight,
    "%luma20.pgm": BoxBottomLeft,
    "%luma21.pgm": BoxBottomCentre,
    "%luma22.pgm": ClockTop,
}
