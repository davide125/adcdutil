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


def getVolumes(filename):
    volumes = {}
    iso = PyCdlib()
    iso.open(filename)
    for root, dirs, files in iso.walk(iso_path="/"):
        for f in files:
            if ".zip" in f.lower():
                dist = os.path.basename(root)
                if dist not in volumes:
                    volumes[dist] = []
                volumes[dist].append(os.path.splitext(f)[0])
    iso.close()

    return volumes


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


def extractVolume(filename, dist, volume, dest=None, overwrite=False):
    if dest is None:
        dest = os.getcwd()

    images = []
    iso = PyCdlib()
    iso.open(filename)
    with tempfile.NamedTemporaryFile(dir=dest) as fp:
        iso.get_file_from_iso_fp(
            fp, iso_path=os.path.join("/", dist, "{}.ZIP;1".format(volume))
        )
        with zipfile.ZipFile(fp.name) as zf:
            contents = zf.namelist()
            for fname in contents:
                image_name = os.path.basename(fname)
                image = os.path.join(dest, image_name)
                checkPath(image, overwrite)
                with open(image, "wb+") as f:
                    f.write(zf.read(fname))
                images.append(image)

    iso.close()

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
    requireCommands(["dasdcopy"])
    volumes = getVolumes(iso)
    if not volumes:
        click.echo("No volumes found!", err=True)
        sys.exit(1)

    for dist, vols in volumes.items():
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
    volumes = getVolumes(iso)
    if volumes:
        for dist, vols in volumes.items():
            click.echo("{}: {}".format(dist, " ".join(sorted(vols))))


if __name__ == "__main__":
    cli()
