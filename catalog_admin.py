"""Validated catalog input and immutable PNG uploads for the administrator."""

import hashlib
import io
import os
import re
import tempfile
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RARITIES = ("Consumer Grade", "Industrial Grade", "Mil-Spec", "Restricted",
            "Classified", "Covert", "Exceedingly Rare", "Contraband")
CONDITIONS = ("Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred")
MEDIA_NAME = re.compile(r"[a-f0-9]{64}\.png")
MAX_UPLOAD = 8 * 1024 * 1024


class SkinCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(default="", max_length=160)
    weapon: str = Field(min_length=1, max_length=60)
    skin: str = Field(min_length=1, max_length=90)
    rarity: str
    condition: str
    price: Decimal = Field(ge=0, le=100000000, max_digits=11, decimal_places=2, allow_inf_nan=False)
    stock: int = Field(ge=0, le=1000000)
    image: str = Field(min_length=8, max_length=2000)
    description: str = Field(default="", max_length=2000)
    active: bool = True

    @field_validator("rarity")
    @classmethod
    def valid_rarity(cls, value):
        for rarity in RARITIES:
            if value.casefold() == rarity.casefold():
                return rarity
        raise ValueError("Noyoblik darajasini ro‘yxatdan tanlang")

    @field_validator("condition")
    @classmethod
    def valid_condition(cls, value):
        aliases = dict(zip(("fn", "mw", "ft", "ww", "bs"), CONDITIONS))
        for condition in CONDITIONS:
            if value.casefold() == condition.casefold():
                return condition
        if value.casefold() in aliases:
            return aliases[value.casefold()]
        raise ValueError("Qurol holatini ro‘yxatdan tanlang")

    @field_validator("image")
    @classmethod
    def valid_image(cls, value):
        if value.startswith("/media/skins/") and MEDIA_NAME.fullmatch(value.removeprefix("/media/skins/")):
            return value
        parts = urlsplit(value)
        if parts.scheme in ("http", "https") and parts.hostname and not parts.username and not parts.password:
            return value
        raise ValueError("PNG yuklang yoki to‘g‘ri HTTPS rasm havolasini kiriting")

    @model_validator(mode="after")
    def display_name(self):
        if not self.name:
            self.name = f"{self.weapon} | {self.skin}"
        return self


def image_directory(database_path):
    # Railway's DATABASE_PATH lives on /data, so images survive deployments.
    return Path(os.getenv("SKIN_IMAGE_DIR", str(Path(database_path).parent / "skin-images")))


def save_png(data, directory):
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(413, "PNG hajmi 8 MB dan oshmasin")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format != "PNG" or getattr(source, "is_animated", False):
                raise ValueError()
            width, height = source.size
            if not 32 <= width <= 4096 or not 32 <= height <= 4096 or width * height > 8_000_000:
                raise HTTPException(422, "Rasm 32–4096 piksel va ko‘pi bilan 8 megapiksel bo‘lsin")
            source.load()
            rgba = source.convert("RGBA")
            transparent = rgba.getchannel("A").getextrema()[0] < 255
            output = io.BytesIO()
            rgba.save(output, format="PNG")
            encoded = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "Yaroqli, animatsiyasiz PNG rasm tanlang") from None
    name = hashlib.sha256(encoded).hexdigest() + ".png"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if not target.exists():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(encoded)
            os.replace(temporary, target)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    return {"url": "/media/skins/" + name, "width": width, "height": height, "transparent": transparent}
