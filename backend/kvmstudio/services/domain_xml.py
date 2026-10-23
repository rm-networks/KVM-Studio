"""Read the parts of a libvirt domain XML that KVM Studio reasons about."""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree


@dataclass(frozen=True, slots=True)
class DiskRef:
    device: str  # "disk", "cdrom", "floppy", "lun"
    source_type: str  # "file", "block", "volume", "network"...
    path: str | None  # file or block device path, when there is one
    target: str
    readonly: bool
    backing_paths: tuple[str, ...]  # chain reported by libvirt, top first


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode(), parser=etree.XMLParser(resolve_entities=False))


def disks(xml: str) -> list[DiskRef]:
    root = _parse(xml)
    result = []
    for disk in root.iterfind("devices/disk"):
        source = disk.find("source")
        path = None
        if source is not None:
            path = source.get("file") or source.get("dev")
        backing = []
        store = disk.find("backingStore")
        while store is not None:
            src = store.find("source")
            if src is not None and (p := src.get("file") or src.get("dev")):
                backing.append(p)
            store = store.find("backingStore")
        target = disk.find("target")
        result.append(
            DiskRef(
                device=disk.get("device", "disk"),
                source_type=disk.get("type", "file"),
                path=path,
                target=target.get("dev", "") if target is not None else "",
                readonly=disk.find("readonly") is not None,
                backing_paths=tuple(backing),
            )
        )
    return result


def nvram_path(xml: str) -> str | None:
    node = _parse(xml).find("os/nvram")
    if node is None:
        return None
    # Recent libvirt may describe the file with a <source file=.../> child.
    source = node.find("source")
    if source is not None and source.get("file"):
        return source.get("file")
    return node.text.strip() if node.text and node.text.strip() else None
