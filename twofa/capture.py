import shutil
import subprocess
from pathlib import Path

from .process import die_with_parent

REGION_TOOLS = ("slurp", "grim", "zbarimg")
FILE_TOOLS = ("zbarimg",)

_ZBAR_QR_ONLY = ["-q", "--raw", "-Sdisable", "-Sqrcode.enable"]


class CaptureError(Exception):
    pass


class CaptureCancelled(CaptureError):
    pass


def missing(tools):
    return [tool for tool in tools if shutil.which(tool) is None]


def _require(tools):
    absent = missing(tools)
    if absent:
        raise CaptureError("missing " + ", ".join(absent))


def _decoded_lines(output):
    return [line.strip() for line in output.decode("utf-8", "replace").splitlines() if line.strip()]


def select_region():
    _require(("slurp",))
    result = subprocess.run(
        ["slurp"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        preexec_fn=die_with_parent,
    )
    geometry = result.stdout.decode("utf-8", "replace").strip()
    if geometry:
        return geometry

    # Empty stderr means the user cancelled.
    complaint = result.stderr.decode("utf-8", "replace").strip()
    if complaint:
        raise CaptureError(f"slurp could not start: {complaint.splitlines()[0]}")
    raise CaptureCancelled("no region was selected")


# Piped into zbar. No image is written.
def scan_region(geometry):
    _require(REGION_TOOLS)
    grim = subprocess.Popen(
        ["grim", "-g", geometry, "-"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        decoder = subprocess.Popen(
            ["zbarimg", *_ZBAR_QR_ONLY, "-"],
            stdin=grim.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    finally:
        grim.stdout.close()

    output, _ = decoder.communicate()
    grim.wait()

    if grim.returncode != 0:
        raise CaptureError("the screen region could not be captured")
    return _decoded_lines(output)


def scan_file(path):
    _require(FILE_TOOLS)
    image = Path(path).expanduser()
    if not image.is_file():
        raise CaptureError(f"no such image: {image}")

    result = subprocess.run(
        ["zbarimg", *_ZBAR_QR_ONLY, str(image)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return _decoded_lines(result.stdout)
