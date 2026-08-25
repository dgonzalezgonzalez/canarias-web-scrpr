from .base import SpiderError
from .emcan import EmcanSpider
from .indeed import IndeedSpider
from .indeed_api import IndeedApiSpider
from .jobspy_spider import JobspySpider
from .sce import SCESpider
from .trabajocantabria import TrabajoCantabriaSpider
from .turijobs import TurijobsSpider

__all__ = [
    "IndeedApiSpider",
    "IndeedSpider",
    "JobspySpider",
    "EmcanSpider",
    "SCESpider",
    "SpiderError",
    "TrabajoCantabriaSpider",
    "TurijobsSpider",
]
