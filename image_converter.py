
import gi
gi.require_version("Nautilus", "4.1")

from gi.repository import Nautilus, GObject, Gio
from PIL import Image, ImageOps

from pathlib import Path
import threading
import logging
import subprocess


# -----------------------------
# Настройки
# -----------------------------

SUPPORTED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp",
    ".bmp", ".tif", ".tiff", ".gif"
}

FORMATS = {
    "PNG": ("PNG", "png"),
    "JPEG": ("JPEG", "jpg"),
    "WEBP": ("WEBP", "webp"),
    "BMP": ("BMP", "bmp"),
    "TIFF": ("TIFF", "tiff"),
}


# -----------------------------
# Логирование
# -----------------------------

LOG_DIR = Path.home() / ".cache"
LOG_DIR.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("ImageConverter")
log.setLevel(logging.DEBUG)

if not log.handlers:
    handler = logging.FileHandler(
        LOG_DIR / "nautilus-image-converter.log"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s: %(message)s"
    ))
    log.addHandler(handler)

log.propagate = False


# -----------------------------
# Вспомогательные функции
# -----------------------------

def get_output_path(source, extension):
    source = Path(source)

    candidate = source.with_suffix("." + extension)

    # Не перезаписываем исходник
    if candidate.resolve() == source.resolve():
        candidate = source.with_name(
            source.stem + "_converted." + extension
        )

    # Не перезаписываем существующие файлы
    counter = 2
    while candidate.exists():
        candidate = source.with_name(
            f"{source.stem}_{counter}.{extension}"
        )
        counter += 1

    return candidate


def convert_image(source, target_format, extension):
    source = Path(source)
    destination = get_output_path(source, extension)

    log.info("1. Opening: %s", source)

    with Image.open(source) as original:
        log.info("2. Image opened: %s", original.size)

        image = ImageOps.exif_transpose(original)
        log.info("3. EXIF processed")

        image.load()
        log.info("4. Pixels loaded")

        if target_format == "JPEG":
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

        elif target_format == "BMP":
            image = image.convert("RGB")

        elif target_format == "WEBP":
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

        elif target_format == "PNG":
            if image.mode == "CMYK":
                image = image.convert("RGB")

        log.info("5. Saving: %s", destination)

        image.save(
            destination,
            target_format,
            **({"quality": 95} if target_format in ("JPEG", "WEBP") else {})
        )

        log.info("6. Saved successfully")

    log.info("Converted: %s -> %s", source, destination)
    return destination


def notify(message):
    try:
        subprocess.run(
            ["notify-send", "Конвертер изображений", message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )
    except Exception:
        pass


def conversion_worker(paths, target_format, extension):
    success = 0
    errors = 0

    log.info("Started conversion to %s", target_format)

    for path in paths:
        try:
            convert_image(path, target_format, extension)
            success += 1
        except Exception:
            errors += 1
            log.exception("Conversion failed: %s", path)

    message = f"Готово: {success}, ошибок: {errors}"
    log.info(message)
    #notify(message)


# -----------------------------
# Расширение Nautilus
# -----------------------------

class ImageConverter(GObject.GObject, Nautilus.MenuProvider):

    __gtype_name__ = "ImageConverterExtension"

    def get_file_items(self, files):

        image_paths = []

        for file in files:
            try:
                if file.get_uri_scheme() != "file":
                    continue

                if file.is_directory():
                    continue

                path = Gio.File.new_for_uri(
                    file.get_uri()
                ).get_path()

                if not path:
                    continue

                if Path(path).suffix.lower() in SUPPORTED_EXTENSIONS:
                    image_paths.append(path)

            except Exception:
                log.exception("Cannot inspect selected file")

        if not image_paths:
            return []

        # Главное меню
        parent = Nautilus.MenuItem(
            name="ImageConverter::convert",
            label="Конвертировать изображение",
            tip="Выбрать формат изображения"
        )

        # Выпадающее подменю
        submenu = Nautilus.Menu()
        parent.set_submenu(submenu)

        for label, (target_format, extension) in FORMATS.items():

            item = Nautilus.MenuItem(
                name=f"ImageConverter::{label}",
                label=label,
                tip=f"Конвертировать в {label}"
            )

            item.connect(
                "activate",
                self.on_convert,
                list(image_paths),
                target_format,
                extension
            )

            submenu.append_item(item)

        return [parent]

    def on_convert( self, menu_item, paths, target_format, extension ):
        log.info(
            "Menu activated: %s, files: %s",
            target_format,
            len(paths)
        )

        conversion_worker(paths, target_format, extension)
