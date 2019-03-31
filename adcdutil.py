#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

import click
from pycdlib import PyCdlib
from pycdlib.pycdlibexception import PyCdlibInvalidInput


def requireCommands(commands):
    missing = []
    for cmd in commands:
        if shutil.which(cmd) is None:
            missing.append(cmd)

    if len(missing) > 0:
        click.echo(
            "Required commands not found: {}".format(" ".join(missing)), err=True
        )
        sys.exit(1)


def walkISO(filename, extension):
    found = {}
    iso = PyCdlib()
    iso.open(filename)
    for root, dirs, files in iso.walk(iso_path="/"):
        for f in files:
            if ".{}".format(extension) in f.lower():
                parent = os.path.basename(root)
                if parent not in found:
                    found[parent] = []
                found[parent].append(os.path.splitext(f)[0])
    iso.close()

    return found


def getTapes(iso):
    return walkISO(iso, "ipl")


def getVolumes(iso):
    return walkISO(iso, "zip")


def checkPath(path, overwrite=False):
    if os.path.exists(path):
        if overwrite:
            click.echo(
                "{} already exists, overwriting as requested".format(path), err=True
            )
            return True
        else:
            click.echo("{} already exists, aborting!".format(path), err=True)
            sys.exit(1)
    else:
        return False


def extractZip(zip_filename):
    with zipfile.ZipFile(zip_filename) as zf:
        contents = zf.namelist()
        try:
            zf.testzip()
            for fname in contents:
                yield (fname, zf.open(fname))
        except NotImplementedError as e:
            for fname in contents:
                p = subprocess.Popen(
                    ["unzip", "-p", zip_filename, fname],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                yield (fname, p.stdout)


def getFileFromIso(iso_filename, dist, filename, dest=None, overwrite=False):
    if dest is None:
        dest = os.getcwd()

    dest_filename = os.path.join(dest, filename)

    iso = PyCdlib()
    iso.open(iso_filename)

    if checkPath(dest_filename, overwrite):
        os.remove(dest_filename)

    try:
        iso.get_file_from_iso(dest_filename, iso_path=os.path.join("/", dist, filename))
    except PyCdlibInvalidInput as e:
        iso.get_file_from_iso(
            dest_filename, iso_path=os.path.join("/", dist, "{};1".format(filename))
        )
    iso.close()

    return dest_filename


def convertTape(filename, dist, tape, compression="zlib", dest=None, overwrite=False):
    if dest is None:
        dest = os.getcwd()

    tape_in = getFileFromIso(filename, dist, "{}.IPL".format(tape), dest, overwrite)
    tape_out = os.path.join(dest, "{}.het".format(tape))

    cmd = ["hetupd"]
    if compression == "zlib":
        cmd.append("-z")
    elif compression == "bzip2":
        cmd.append("-b")
    elif compression == "none":
        cmd.append("-d")
    cmd += [tape_in, tape_out]

    subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
    )

    os.remove(tape_in)

    return tape_out


def extractVolume(filename, dist, volume, dest=None, overwrite=False):
    if dest is None:
        dest = os.getcwd()

    images = []

    zip_filename = getFileFromIso(
        filename, dist, "{}.ZIP".format(volume), dest, overwrite
    )
    for fname, zfp in extractZip(zip_filename):
        image_name = os.path.basename(fname)
        image = os.path.join(dest, image_name)
        checkPath(image, overwrite)
        with open(image, "wb+") as f:
            f.write(zfp.read())
        images.append(image)

    os.remove(zip_filename)

    return sorted(images)


@click.group()
def cli():
    pass


@cli.command()
@click.option("-d", "--destination", type=click.Path(exists=True, file_okay=False))
@click.option("-f", "--force/--no-force", default=False)
@click.option(
    "-c", "--compression", type=click.Choice(["zlib", "bzip2", "none"]), default="zlib"
)
@click.option("-q", "--quiet/--verbose", default=False)
@click.option(
    "-o",
    "--output-format",
    type=click.Choice(["CKD", "CCKD", "FBA", "CFBA"]),
    default="CCKD",
)
@click.argument("iso", type=click.Path(exists=True, dir_okay=False))
def convert(destination, force, compression, quiet, output_format, iso):
    requireCommands(["dasdcopy", "hetupd", "unzip"])
    iso_tapes = getTapes(iso)
    if not iso_tapes:
        click.echo("No tapes found.", err=True)
    for dist, tapes in iso_tapes.items():
        for tape in tapes:
            if not quiet:
                click.echo("Converting {} tape {}...".format(dist, tape))
            tape_out = convertTape(iso, dist, tape, compression, destination, force)
            if not quiet:
                click.echo(
                    "{} tape {} converted to {}".format(
                        dist, tape, os.path.basename(tape_out)
                    )
                )

    iso_volumes = getVolumes(iso)
    if not iso_volumes:
        click.echo("No volumes found.", err=True)

    for dist, vols in iso_volumes.items():
        for vol in vols:
            if not quiet:
                click.echo("Extracting {} volume {}...".format(dist, vol))
            images = extractVolume(iso, dist, vol, destination, force)
            if len(images) == 0:
                click.echo("No images extracted!", err=True)
                sys.exit(1)
            elif len(images) == 1:
                vol_in = images[0]
                if not quiet:
                    click.echo(
                        "Found single-file image: {}".format(os.path.basename(vol_in))
                    )
            else:
                vol_in = "{}.img".format(images[0].split("_")[0])
                if not quiet:
                    click.echo(
                        "Found multi-file image, converting to single-file: {}".format(
                            os.path.basename(vol_in)
                        )
                    )
                cmd = ["dasdcopy", "-q"]
                if checkPath(vol_in, force):
                    cmd.append("-r")
                cmd += ["-lfs", images[0], vol_in]
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
                for img in images:
                    os.remove(img)

            vol_out = "{}.{}".format(os.path.splitext(vol_in)[0], output_format.lower())
            if not quiet:
                click.echo("Converting to {}...".format(output_format))
            cmd = ["dasdcopy", "-q"]
            if checkPath(vol_out, force):
                cmd.append("-r")
            if compression == "zlib":
                cmd.append("-z")
            elif compression == "bzip2":
                cmd.append("-bz2")
            elif compression == "none":
                cmd.append("-0")
            cmd += ["-o", output_format.upper(), vol_in, vol_out]
            subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
            os.remove(vol_in)
            if not quiet:
                click.echo(
                    "{} volume {} converted to {}".format(
                        dist, vol, os.path.basename(vol_out)
                    )
                )


@cli.command()
@click.argument("iso", type=click.Path(exists=True, dir_okay=False))
def dump(iso):
    iso_tapes = getTapes(iso)
    if iso_tapes:
        for dist, tapes in iso_tapes.items():
            click.echo("{} tapes: {}".format(dist, " ".join(sorted(tapes))))

    iso_volumes = getVolumes(iso)
    if iso_volumes:
        for dist, vols in iso_volumes.items():
            click.echo("{} volumes: {}".format(dist, " ".join(sorted(vols))))


if __name__ == "__main__":
    cli()
