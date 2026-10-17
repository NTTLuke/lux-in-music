"""Local song artwork, kept outside music-model requests."""

import base64
import binascii
import io
import json
from pathlib import Path

from .vibe import load_catalog, validate_image, MAX_VIBE_IMAGES


def compose_cover(images: list[bytes]) -> bytes:
    if len(images) == 1:
        return images[0]
    from PIL import Image, ImageOps
    layouts = {
        2: [(0, 0, .5, 1), (.5, 0, 1, 1)],
        3: [(0, 0, .5, 1), (.5, 0, 1, .5), (.5, .5, 1, 1)],
        4: [(c / 2, r / 2, (c + 1) / 2, (r + 1) / 2) for r in range(2) for c in range(2)],
        5: [(0, 0, .5, 1)] + [(.5 + c / 4, r / 2, .75 + c / 4, (r + 1) / 2) for r in range(2) for c in range(2)],
    }
    canvas = Image.new("RGB", (1200, 1200), (12, 11, 14))
    for data, box in zip(images, layouts[len(images)]):
        x, y, right, bottom = [round(value * 1200) for value in box]
        with Image.open(io.BytesIO(data)) as image:
            tile = ImageOps.fit(image, (right - x - 6, bottom - y - 6))
            canvas.paste(tile, (x + 3, y + 3))
            tile.close()
    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=90)
    canvas.close()
    return output.getvalue()


def prepare_vibe_artwork(encoded: str | None, entry_id: str | None, images: list[dict] | None = None) -> dict | None:
    if encoded is None and entry_id is None and images is None:
        return None
    if images is not None and encoded is not None:
        raise ValueError("Use one Vibe image collection per song.")
    items = images if images is not None else [{"image": encoded, "entry_id": entry_id}]
    valid_ids = {row["id"] for row in load_catalog()}
    if (not 1 <= len(items) <= MAX_VIBE_IMAGES or entry_id is not None and entry_id not in valid_ids
            or any(not item.get("image") or item.get("entry_id") not in valid_ids for item in items)):
        raise ValueError("Choose a Vibe image and analyze it before using it as a cover.")
    prepared = []
    for item in items:
        try:
            data = base64.b64decode(item["image"], validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("The Vibe cover is not a valid image upload.") from error
        image = validate_image(data)
        try:
            image.thumbnail((2048, 2048))
            image.info.clear()
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=90)
            prepared.append({"image": output.getvalue(), "entry_id": item["entry_id"]})
        finally:
            image.close()
    return {"image": compose_cover([item["image"] for item in prepared]), "images": prepared,
            "entry_id": entry_id or prepared[0]["entry_id"]}


def attach_vibe_artwork(meta_path: Path, artwork: dict) -> None:
    """Give each completed song its own cover, including generated variations."""
    metadata = json.loads(meta_path.read_text())
    path = meta_path.with_suffix(".vibe.jpg")
    path.write_bytes(artwork["image"])
    metadata.setdefault("artifacts", {})["vibe_image"] = path.name
    metadata["vibe"] = {"source": "image", "entry_id": artwork["entry_id"]}
    if artwork.get("images"):
        gallery = []
        for index, item in enumerate(artwork["images"]):
            image_path = path if len(artwork["images"]) == 1 else meta_path.with_suffix(f".vibe-{index + 1}.jpg")
            if image_path != path:
                image_path.write_bytes(item["image"])
                metadata["artifacts"][f"vibe_image_{index + 1}"] = image_path.name
            gallery.append({"file": image_path.name, "entry_id": item["entry_id"]})
        metadata["vibe"].update(images=gallery, image_count=len(gallery))
    meta_path.write_text(json.dumps(metadata, indent=2))
